import logging
from celery import shared_task
from django.utils import timezone
from django.db.models import Q

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# TASK 1 — Executar gatilhos baseados em tempo
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(name='tickets.avaliar_gatilhos_tempo', bind=True, max_retries=3)
def avaliar_gatilhos_tempo(self):
    """
    Avalia gatilhos com condições baseadas em tempo para todos os tickets abertos.
    Roda a cada 5 minutos via Celery Beat.

    Detecta condições do tipo:
      - "Ação - Somente a última: Não registrada a X horas"
      - "Tempo no status atual > X horas"
      - "Tempo total aberto > X horas"
    """
    try:
        from apps.tickets.models import Ticket, Gatilho, StatusBase
        from apps.tickets.signals import avaliar_condicoes, executar_acoes

        # Tickets abertos (excluir fechados e cancelados)
        tickets_abertos = Ticket.objects.filter(
            status__status_base__in=[
                StatusBase.NOVO,
                StatusBase.EM_ATENDIMENTO,
                StatusBase.PARADO,
            ]
        ).select_related(
            'status', 'cliente', 'responsavel',
            'solicitante', 'categoria', 'urgencia'
        )

        total_avaliados = 0
        total_disparados = 0

        for ticket in tickets_abertos:
            gatilhos = Gatilho.objects.filter(
                cliente=ticket.cliente,
                ativo=True
            ).order_by('ordem')

            for gatilho in gatilhos:
                condicoes = gatilho.condicoes or {}
                if not _tem_condicao_tempo(condicoes):
                    continue  # Pula gatilhos sem condição de tempo

                try:
                    if avaliar_condicoes(condicoes, ticket, None, 'tempo'):
                        executar_acoes(gatilho, ticket)
                        total_disparados += 1
                        logger.info(
                            f"[TASK/GATILHO] '{gatilho.nome}' disparado no ticket #{ticket.numero}"
                        )
                except Exception as e:
                    logger.error(
                        f"[TASK/GATILHO] Erro no gatilho '{gatilho.nome}' "
                        f"ticket #{ticket.numero}: {e}"
                    )

            total_avaliados += 1

        logger.info(
            f"[TASK] avaliar_gatilhos_tempo: {total_avaliados} tickets avaliados, "
            f"{total_disparados} gatilhos disparados."
        )
        return {'avaliados': total_avaliados, 'disparados': total_disparados}

    except Exception as exc:
        logger.error(f"[TASK] avaliar_gatilhos_tempo falhou: {exc}")
        raise self.retry(exc=exc, countdown=60)


def _tem_condicao_tempo(condicoes):
    """Verifica recursivamente se o JSON de condições contém alguma baseada em tempo."""

    def _buscar(obj):
        if isinstance(obj, dict):
            campo = obj.get('campo', '')
            op = obj.get('operador', '')
            if campo.startswith('tempo.') or op in ('nao_registrada', 'maior_que', 'menor_que', 'entre'):
                return True
            return any(_buscar(v) for v in obj.values())
        if isinstance(obj, list):
            return any(_buscar(i) for i in obj)
        return False

    return _buscar(condicoes)


# ─────────────────────────────────────────────────────────────────────────────
# TASK 2 — Alertas de SLA
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(name='tickets.verificar_sla', bind=True, max_retries=3)
def verificar_sla(self):
    """
    Verifica tickets com SLA próximo do vencimento ou já vencido.
    Cria notificações in-app e dispara e-mails de alerta.
    Roda a cada 15 minutos via Celery Beat.

    Thresholds de alerta:
      - 75% do prazo consumido  → alerta amarelo
      - 90% do prazo consumido  → alerta laranja
      - 100% (vencido)          → alerta vermelho + notificação urgente
    """
    try:
        from apps.tickets.models import Ticket, StatusBase, NotificacaoTicket
        from django.core.mail import send_mail
        from django.conf import settings

        agora = timezone.now()

        tickets = Ticket.objects.filter(
            previsao_solucao__isnull=False,
            status__status_base__in=[StatusBase.NOVO, StatusBase.EM_ATENDIMENTO, StatusBase.PARADO]
        ).select_related(
            'status', 'responsavel', 'solicitante', 'cliente', 'regra_sla_aplicada'
        )

        alertas_criados = 0

        for ticket in tickets:
            if not ticket.previsao_solucao:
                continue

            total_seg = (ticket.previsao_solucao - ticket.criado_em).total_seconds()
            if total_seg <= 0:
                continue

            usado_seg = (agora - ticket.criado_em).total_seconds()
            pct = (usado_seg / total_seg) * 100

            # Verifica se já existe notificação de SLA recente (nas últimas 4h)
            ja_notificado = NotificacaoTicket.objects.filter(
                ticket=ticket,
                tipo__in=['sla_proximo', 'sla_vencido'],
                criado_em__gte=agora - timezone.timedelta(hours=4)
            ).exists()

            if ja_notificado:
                continue

            if pct >= 100:
                tipo = 'sla_vencido'
                titulo = f'SLA VENCIDO — Ticket #{ticket.numero}'
                msg = f'Previsão: {ticket.previsao_solucao.strftime("%d/%m %H:%M")}. {ticket.assunto}'
                _criar_alerta_sla(ticket, tipo, titulo, msg)
                alertas_criados += 1

            elif pct >= 90:
                tipo = 'sla_proximo'
                titulo = f'SLA em 10% — Ticket #{ticket.numero}'
                msg = f'Previsão: {ticket.previsao_solucao.strftime("%d/%m %H:%M")}'
                _criar_alerta_sla(ticket, tipo, titulo, msg)
                alertas_criados += 1

            elif pct >= 75:
                tipo = 'sla_proximo'
                titulo = f'SLA em 25% — Ticket #{ticket.numero}'
                msg = f'Previsão: {ticket.previsao_solucao.strftime("%d/%m %H:%M")}'
                _criar_alerta_sla(ticket, tipo, titulo, msg)
                alertas_criados += 1

        logger.info(f"[TASK] verificar_sla: {alertas_criados} alertas criados.")
        return {'alertas': alertas_criados}

    except Exception as exc:
        logger.error(f"[TASK] verificar_sla falhou: {exc}")
        raise self.retry(exc=exc, countdown=120)


def _criar_alerta_sla(ticket, tipo, titulo, mensagem):
    """Cria notificação in-app e envia e-mail de alerta de SLA."""
    from apps.tickets.models import NotificacaoTicket
    from django.core.mail import send_mail
    from django.conf import settings

    destinatarios = []

    if ticket.responsavel:
        NotificacaoTicket.objects.create(
            usuario=ticket.responsavel,
            ticket=ticket,
            tipo=tipo,
            titulo=titulo,
            mensagem=mensagem,
        )
        if ticket.responsavel.email:
            destinatarios.append(ticket.responsavel.email)

    if ticket.equipe if hasattr(ticket, 'equipe') else None:
        for agente in ticket.equipe.agentes.filter(is_active=True).exclude(
                pk=ticket.responsavel_id if ticket.responsavel else None):
            NotificacaoTicket.objects.create(
                usuario=agente,
                ticket=ticket,
                tipo=tipo,
                titulo=titulo,
                mensagem=mensagem,
            )

    # Envia e-mail se houver destinatários e configuração de e-mail
    if destinatarios:
        try:
            send_mail(
                subject=f'[ALERTA SLA] {titulo}',
                message=f'{mensagem}\n\nAcesse: {getattr(settings, "SITE_URL", "")}/tickets/tickets/{ticket.pk}/',
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', ''),
                recipient_list=destinatarios,
                fail_silently=True,
            )
        except Exception as e:
            logger.error(f"[TASK/SLA] Erro ao enviar e-mail de alerta: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# TASK 3 — Fechamento automático de tickets resolvidos
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(name='tickets.fechar_tickets_resolvidos', bind=True, max_retries=3)
def fechar_tickets_resolvidos(self, dias=7):
    """
    Fecha automaticamente tickets que estão em status RESOLVIDO
    há mais de `dias` dias sem interação.
    Roda diariamente via Celery Beat.
    """
    try:
        from apps.tickets.models import Ticket, Status, StatusBase, AcaoTicket, HistoricoTicket
        from django.db.models import Max

        limite = timezone.now() - timezone.timedelta(days=dias)

        tickets_resolvidos = Ticket.objects.filter(
            status__status_base=StatusBase.RESOLVIDO,
            resolvido_em__lt=limite,
        ).select_related('status', 'cliente', 'solicitante')

        fechados = 0

        for ticket in tickets_resolvidos:
            # Verifica se houve alguma ação após a resolução
            ultima_acao = ticket.acoes.order_by('-criado_em').first()
            if ultima_acao and ultima_acao.criado_em > limite:
                continue  # Teve atividade recente, não fecha

            # Busca status FECHADO do cliente
            status_fechado = Status.objects.filter(
                cliente=ticket.cliente,
                status_base=StatusBase.FECHADO,
                ativo=True
            ).first()

            if not status_fechado:
                continue

            status_anterior = ticket.status
            ticket._executando_gatilho = True  # Evita recursão de signals
            ticket.status = status_fechado
            ticket.fechado_em = timezone.now()
            ticket.save(update_fields=['status', 'fechado_em'])
            ticket._executando_gatilho = False

            AcaoTicket.objects.create(
                ticket=ticket,
                tipo='interna',
                autor=ticket.cliente,
                conteudo=f'[AUTOMÁTICO] Ticket fechado automaticamente após {dias} dias sem interação desde a resolução.',
            )

            HistoricoTicket.objects.create(
                ticket=ticket,
                usuario=ticket.cliente,
                campo='status',
                valor_anterior=str(status_anterior),
                valor_novo=str(status_fechado),
            )

            fechados += 1

        logger.info(f"[TASK] fechar_tickets_resolvidos: {fechados} tickets fechados.")
        return {'fechados': fechados}

    except Exception as exc:
        logger.error(f"[TASK] fechar_tickets_resolvidos falhou: {exc}")
        raise self.retry(exc=exc, countdown=300)


# ─────────────────────────────────────────────────────────────────────────────
# TASK 4 — Processar e-mails (já existia, agora via Celery)
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(name='tickets.processar_emails', bind=True, max_retries=2)
def processar_emails(self):
    """
    Processa e-mails recebidos e cria/atualiza tickets.
    Roda a cada 5 minutos via Celery Beat.
    """
    try:
        from django.core.management import call_command
        call_command('process_ticket_emails', '--mark-read', '--limit=50')
        logger.info("[TASK] processar_emails: concluído.")
    except Exception as exc:
        logger.error(f"[TASK] processar_emails falhou: {exc}")
        raise self.retry(exc=exc, countdown=60)


# ─────────────────────────────────────────────────────────────────────────────
# TASK 5 — Limpeza de notificações antigas
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(name='tickets.limpar_notificacoes', bind=True, max_retries=2)
def limpar_notificacoes(self, dias=30):
    """
    Remove notificações lidas com mais de `dias` dias.
    Roda semanalmente via Celery Beat.
    """
    try:
        from apps.tickets.models import NotificacaoTicket
        limite = timezone.now() - timezone.timedelta(days=dias)
        total, _ = NotificacaoTicket.objects.filter(
            lida=True,
            lida_em__lt=limite
        ).delete()
        logger.info(f"[TASK] limpar_notificacoes: {total} removidas.")
        return {'removidas': total}
    except Exception as exc:
        logger.error(f"[TASK] limpar_notificacoes falhou: {exc}")
        raise self.retry(exc=exc, countdown=300)


# ─────────────────────────────────────────────────────────────────────────────
# TASK 6 — Enviar pesquisa de satisfação
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(name='tickets.enviar_pesquisa_satisfacao', bind=True, max_retries=3)
def enviar_pesquisa_satisfacao(self, horas_apos_fechamento=24):
    """
    Envia pesquisa de satisfação (CSAT) para tickets fechados há X horas
    que ainda não receberam a pesquisa.
    Roda a cada hora via Celery Beat.
    """
    try:
        from apps.tickets.models import Ticket, PesquisaSatisfacao, StatusBase
        from django.core.mail import send_mail
        from django.conf import settings

        limite = timezone.now() - timezone.timedelta(hours=horas_apos_fechamento)

        tickets_sem_pesquisa = Ticket.objects.filter(
            status__status_base=StatusBase.FECHADO,
            fechado_em__lte=limite,
            pesquisa_satisfacao__isnull=True,
        ).select_related('solicitante', 'status')

        enviadas = 0
        site_url = getattr(settings, 'SITE_URL', 'http://localhost:8000')

        for ticket in tickets_sem_pesquisa:
            if not ticket.solicitante or not ticket.solicitante.email:
                continue

            pesquisa = PesquisaSatisfacao.objects.create(ticket=ticket)

            try:
                send_mail(
                    subject=f'Como foi o atendimento? Ticket #{ticket.numero}',
                    message=f"""Olá {ticket.solicitante.get_full_name() or ticket.solicitante.username},

Seu ticket #{ticket.numero} "{ticket.assunto}" foi encerrado.

Gostaríamos de saber como foi o atendimento. Por favor, acesse o link abaixo e avalie:

{site_url}/tickets/tickets/{ticket.pk}/avaliar/

Sua opinião é muito importante para melhorarmos nosso suporte.

Atenciosamente,
Equipe de Suporte""",
                    from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', ''),
                    recipient_list=[ticket.solicitante.email],
                    fail_silently=True,
                )
                enviadas += 1
            except Exception as e:
                logger.error(f"[TASK/CSAT] Erro ao enviar para ticket #{ticket.numero}: {e}")

        logger.info(f"[TASK] enviar_pesquisa_satisfacao: {enviadas} enviadas.")
        return {'enviadas': enviadas}

    except Exception as exc:
        logger.error(f"[TASK] enviar_pesquisa_satisfacao falhou: {exc}")
        raise self.retry(exc=exc, countdown=300)