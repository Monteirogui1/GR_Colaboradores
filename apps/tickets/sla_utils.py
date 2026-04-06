from datetime import timedelta
import logging

logger = logging.getLogger(__name__)


def calcular_prazo_uteis(dt_inicio, horas_prazo, horarios_qs, feriados_qs):
    """
    Calcula dt_inicio + horas_prazo em horas úteis reais,
    respeitando janelas de atendimento e feriados.

    Args:
        dt_inicio    : datetime aware — início do prazo (UTC ou local)
        horas_prazo  : int/float     — horas de SLA a consumir
        horarios_qs  : QuerySet[HorarioAtendimento] — janelas ativas do cliente
        feriados_qs  : QuerySet[Feriado]             — feriados do cliente

    Returns:
        datetime aware — previsão de solução
    """
    from django.utils import timezone

    if not horarios_qs.exists():
        return dt_inicio + timedelta(hours=horas_prazo)

    # Monta mapa dia_semana → [(inicio, fim), ...]
    janelas = {}
    for h in horarios_qs.filter(ativo=True):
        janelas.setdefault(h.dia_semana, []).append((h.hora_inicio, h.hora_fim))
    for dia in janelas:
        janelas[dia].sort()

    # Cache de datas feriado
    feriados = set()
    for f in feriados_qs:
        if f.recorrente:
            for ano in range(dt_inicio.year, dt_inicio.year + 6):
                try:
                    feriados.add(f.data.replace(year=ano))
                except ValueError:
                    pass
        else:
            feriados.add(f.data)

    def proxima_janela(dt):
        """Retorna o próximo instante dentro de uma janela de atendimento."""
        for dias_a_frente in range(8):
            candidate = dt + timedelta(days=dias_a_frente)
            if candidate.date() in feriados:
                dt = dt.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=dias_a_frente + 1)
                continue
            dia = candidate.weekday()
            for inicio, fim in janelas.get(dia, []):
                hora_cand = candidate.time() if dias_a_frente == 0 else None
                if hora_cand is None:
                    # Próximo dia: começa no início da janela
                    return candidate.replace(
                        hour=inicio.hour, minute=inicio.minute,
                        second=0, microsecond=0
                    )
                if hora_cand < fim:
                    if hora_cand >= inicio:
                        return candidate  # Já está dentro da janela
                    else:
                        return candidate.replace(
                            hour=inicio.hour, minute=inicio.minute,
                            second=0, microsecond=0
                        )
        return dt + timedelta(days=1)  # Fallback

    atual = dt_inicio

    # Se não está numa janela útil, avança
    def em_janela_util(dt):
        if dt.date() in feriados:
            return False
        dia = dt.weekday()
        hora = dt.time()
        return any(i <= hora < f for i, f in janelas.get(dia, []))

    if not em_janela_util(atual):
        atual = proxima_janela(atual)

    horas_restantes = float(horas_prazo)
    MAX_ITER = int(horas_prazo) * 20 + 1000

    for _ in range(MAX_ITER):
        if horas_restantes <= 0:
            break

        if not em_janela_util(atual):
            atual = proxima_janela(atual)
            continue

        dia = atual.weekday()
        hora_atual = atual.time()

        # Encontra fim da janela corrente
        fim_janela_time = None
        for inicio, fim in janelas.get(dia, []):
            if inicio <= hora_atual < fim:
                fim_janela_time = fim
                break

        if fim_janela_time is None:
            atual = proxima_janela(atual)
            continue

        fim_janela_dt = atual.replace(
            hour=fim_janela_time.hour,
            minute=fim_janela_time.minute,
            second=0, microsecond=0
        )

        horas_disponíveis = (fim_janela_dt - atual).total_seconds() / 3600

        if horas_restantes <= horas_disponíveis:
            atual = atual + timedelta(hours=horas_restantes)
            horas_restantes = 0
        else:
            horas_restantes -= horas_disponíveis
            atual = proxima_janela(fim_janela_dt + timedelta(seconds=1))

    return atual


def calcular_sla_ticket(ticket):
    """
    Versão atualizada de Ticket.calcular_sla() com suporte a horas úteis reais
    e subtração do tempo pausado.

    Substituir o método calcular_sla() existente no modelo Ticket por:

        from apps.tickets.sla_utils import calcular_sla_ticket
        def calcular_sla(self):
            calcular_sla_ticket(self)
    """
    from apps.tickets.models import ContratoSLA, HorarioAtendimento, Feriado, Ticket

    if ticket.previsao_manual:
        return

    contrato = ticket.contrato_sla or ContratoSLA.objects.filter(
        cliente=ticket.cliente,
        is_padrao=True,
        ativo=True
    ).first()

    if not contrato:
        return

    for regra in contrato.regras.filter(ativo=True).order_by('ordem'):
        if not regra.aplica_ao_ticket(ticket):
            continue

        ticket.regra_sla_aplicada = regra
        ticket.contrato_sla = contrato

        # Subtrai o tempo já pausado do início efetivo
        dt_inicio = ticket.criado_em
        if ticket.tempo_pausado and ticket.tempo_pausado.total_seconds() > 0:
            dt_inicio = dt_inicio + ticket.tempo_pausado

        prazo_horas = regra.prazo_solucao

        if regra.tipo_horario == 'uteis':
            horarios = HorarioAtendimento.objects.filter(cliente=ticket.cliente, ativo=True)
            feriados = Feriado.objects.filter(cliente=ticket.cliente)
            previsao = calcular_prazo_uteis(dt_inicio, prazo_horas, horarios, feriados)
        else:
            previsao = dt_inicio + timedelta(hours=prazo_horas)

        ticket.previsao_solucao = previsao

        Ticket.objects.filter(pk=ticket.pk).update(
            regra_sla_aplicada=ticket.regra_sla_aplicada,
            contrato_sla=ticket.contrato_sla,
            previsao_solucao=ticket.previsao_solucao,
        )
        break