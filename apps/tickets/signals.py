import logging
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

logger = logging.getLogger(__name__)


@receiver(pre_save, sender='tickets.Ticket')
def capturar_estado_anterior_ticket(sender, instance, **kwargs):
    if instance.pk:
        try:
            anterior = sender.objects.get(pk=instance.pk)
            instance._estado_anterior = {
                'status_id': anterior.status_id,
                'status_base': anterior.status.status_base,
                'categoria_id': anterior.categoria_id,
                'urgencia_id': anterior.urgencia_id,
                'servico_id': anterior.servico_id,
                'justificativa_id': anterior.justificativa_id,
                'responsavel_id': anterior.responsavel_id,
                'assunto': anterior.assunto,
                'tipo_ticket': anterior.tipo_ticket,
                'canal_abertura': anterior.canal_abertura,
            }
        except sender.DoesNotExist:
            instance._estado_anterior = None
    else:
        instance._estado_anterior = None


@receiver(post_save, sender='tickets.Ticket')
def dispatcher_gatilhos_ticket(sender, instance, created, **kwargs):
    if getattr(instance, '_executando_gatilho', False):
        return

    if created:
        notificar_ticket_criado(instance)
    else:
        anterior = getattr(instance, '_estado_anterior', {})
        if anterior and anterior.get('status_id') != instance.status_id:
            from apps.tickets.models import Status as StatusModel
            try:
                st_ant = StatusModel.objects.get(pk=anterior['status_id'])
                notificar_status_alterado(instance, st_ant.nome)
            except Exception:
                pass
    try:
        from apps.tickets.models import Gatilho
        gatilhos = Gatilho.objects.filter(cliente=instance.cliente, ativo=True).order_by('ordem')
        if not gatilhos.exists():
            return
        anterior = getattr(instance, '_estado_anterior', None)
        evento = 'criacao' if created else 'atualizacao'
        for gatilho in gatilhos:
            try:
                if avaliar_condicoes(gatilho.condicoes, instance, anterior, evento):
                    executar_acoes(gatilho, instance)
                    logger.info(f"[GATILHO] '{gatilho.nome}' executado no ticket #{instance.numero}")
            except Exception as e:
                logger.error(f"[GATILHO] Erro ao executar '{gatilho.nome}' no ticket #{instance.numero}: {e}")
    except Exception as e:
        logger.error(f"[GATILHO] Erro no dispatcher para ticket #{instance.numero}: {e}")


@receiver(post_save, sender='tickets.AcaoTicket')
def dispatcher_gatilhos_acao(sender, instance, created, **kwargs):
    if not created:
        return
    ticket = instance.ticket
    if getattr(ticket, '_executando_gatilho', False):
        return
    try:
        from apps.tickets.models import Gatilho
        gatilhos = Gatilho.objects.filter(cliente=ticket.cliente, ativo=True).order_by('ordem')
        for gatilho in gatilhos:
            try:
                condicoes = gatilho.condicoes or {}
                if _tem_condicao_de_acao(condicoes):
                    if avaliar_condicoes(condicoes, ticket, None, 'nova_acao', ultima_acao=instance):
                        executar_acoes(gatilho, ticket)
                        if instance.tipo == 'publica':
                            notificar_nova_acao(instance)
                        logger.info(f"[GATILHO/ACAO] '{gatilho.nome}' executado no ticket #{ticket.numero}")
            except Exception as e:
                logger.error(f"[GATILHO/ACAO] Erro ao executar '{gatilho.nome}': {e}")
    except Exception as e:
        logger.error(f"[GATILHO/ACAO] Erro no dispatcher de ação: {e}")


def _tem_condicao_de_acao(condicoes):
    def _buscar(obj):
        if isinstance(obj, dict):
            if 'acao' in obj.get('campo', ''):
                return True
            return any(_buscar(v) for v in obj.values())
        if isinstance(obj, list):
            return any(_buscar(item) for item in obj)
        return False

    return _buscar(condicoes)


def avaliar_condicoes(condicoes, ticket, anterior, evento, ultima_acao=None):
    if not condicoes:
        return False
    if 'campo' in condicoes and 'operador' in condicoes:
        return _avaliar_condicao_simples(condicoes, ticket, anterior, evento, ultima_acao)
    if 'todas' in condicoes:
        lista = condicoes['todas']
        if not lista:
            return False
        return all(avaliar_condicoes(c, ticket, anterior, evento, ultima_acao) for c in lista)
    if 'qualquer' in condicoes:
        lista = condicoes['qualquer']
        if not lista:
            return False
        return any(avaliar_condicoes(c, ticket, anterior, evento, ultima_acao) for c in lista)
    return False


def _avaliar_condicao_simples(cond, ticket, anterior, evento, ultima_acao=None):
    campo = cond.get('campo', '')
    operador = cond.get('operador', '')
    valor = cond.get('valor')
    valor_atual = _extrair_valor_campo(campo, ticket, ultima_acao)
    valor_anterior = _extrair_valor_campo_anterior(campo, anterior) if anterior else None
    return _aplicar_operador(operador, valor_atual, valor_anterior, valor, cond)


def _extrair_valor_campo(campo, ticket, ultima_acao=None):
    mapa = {
        'ticket.status': lambda t: str(t.status_id) if t.status_id else None,
        'ticket.status_base': lambda t: t.status.status_base if t.status else None,
        'ticket.status.nome': lambda t: t.status.nome if t.status else None,
        'ticket.categoria': lambda t: str(t.categoria_id) if t.categoria_id else None,
        'ticket.urgencia': lambda t: str(t.urgencia_id) if t.urgencia_id else None,
        'ticket.servico': lambda t: str(t.servico_id) if t.servico_id else None,
        'ticket.justificativa': lambda t: str(t.justificativa_id) if t.justificativa_id else None,
        'ticket.justificativa.nome': lambda t: t.justificativa.nome if t.justificativa else None,
        'ticket.responsavel': lambda t: str(t.responsavel_id) if t.responsavel_id else None,
        'ticket.solicitante': lambda t: str(t.solicitante_id) if t.solicitante_id else None,
        'ticket.solicitante.tipo': lambda t: 'agente' if t.solicitante and t.solicitante.is_staff else 'cliente',
        'ticket.assunto': lambda t: t.assunto or '',
        'ticket.tipo': lambda t: t.tipo_ticket,
        'ticket.tipo_ticket': lambda t: t.tipo_ticket,
        'ticket.canal': lambda t: t.canal_abertura,
        'ticket.canal_abertura': lambda t: t.canal_abertura,
        'ticket.tags': lambda t: t.tags or [],
    }
    if campo.startswith('acao.ultima') and ultima_acao is not None:
        if campo == 'acao.ultima.tipo':
            return ultima_acao.tipo
        if campo == 'acao.ultima.autor':
            return str(ultima_acao.autor_id)
        if campo == 'acao.ultima.autor.tipo':
            return 'agente' if ultima_acao.autor.is_staff else 'cliente'
    if campo == 'tempo.status.corrido':
        ref = ticket.pausado_em or ticket.atualizado_em or ticket.criado_em
        return (timezone.now() - ref).total_seconds() / 3600
    if campo == 'tempo.total.corrido':
        return (timezone.now() - ticket.criado_em).total_seconds() / 3600
    if campo.startswith('acao.ultima'):
        return None
    fn = mapa.get(campo)
    if fn:
        try:
            return fn(ticket)
        except Exception:
            return None
    return None


def _extrair_valor_campo_anterior(campo, anterior):
    if anterior is None:
        return None
    mapa = {
        'ticket.status': lambda a: str(a.get('status_id')),
        'ticket.status_base': lambda a: a.get('status_base'),
        'ticket.categoria': lambda a: str(a.get('categoria_id')),
        'ticket.urgencia': lambda a: str(a.get('urgencia_id')),
        'ticket.servico': lambda a: str(a.get('servico_id')),
        'ticket.justificativa': lambda a: str(a.get('justificativa_id')),
        'ticket.responsavel': lambda a: str(a.get('responsavel_id')),
        'ticket.assunto': lambda a: a.get('assunto', ''),
        'ticket.tipo_ticket': lambda a: a.get('tipo_ticket'),
        'ticket.canal_abertura': lambda a: a.get('canal_abertura'),
    }
    fn = mapa.get(campo)
    if fn:
        try:
            return fn(anterior)
        except Exception:
            return None
    return None


def _aplicar_operador(operador, valor_atual, valor_anterior, valor_esperado, cond):
    ve = str(valor_esperado) if valor_esperado is not None else ''
    if operador == 'igual':
        if isinstance(valor_atual, list):
            return ve in [str(v) for v in valor_atual]
        return str(valor_atual) == ve if valor_atual is not None else False
    if operador == 'diferente':
        if isinstance(valor_atual, list):
            return ve not in [str(v) for v in valor_atual]
        return str(valor_atual) != ve if valor_atual is not None else True
    if operador == 'contem':
        if isinstance(valor_atual, list):
            return ve in [str(v) for v in valor_atual]
        return ve in str(valor_atual) if valor_atual else False
    if operador == 'nao_contem':
        if isinstance(valor_atual, list):
            return ve not in [str(v) for v in valor_atual]
        return ve not in str(valor_atual) if valor_atual else True
    if operador == 'comeca':
        return str(valor_atual).startswith(ve) if valor_atual else False
    if operador == 'vazio':
        if isinstance(valor_atual, list):
            return len(valor_atual) == 0
        return valor_atual in (None, '', 'None')
    if operador == 'nao_vazio':
        if isinstance(valor_atual, list):
            return len(valor_atual) > 0
        return valor_atual not in (None, '', 'None')
    if operador == 'alterado':
        return valor_atual != valor_anterior
    if operador == 'alterado_de':
        return (valor_anterior is not None and str(valor_anterior) == ve and valor_atual != valor_anterior)
    if operador == 'alterado_para':
        return (valor_atual is not None and str(valor_atual) == ve and valor_atual != valor_anterior)
    if operador in ('maior_que', 'nao_registrada'):
        try:
            return float(valor_atual or 0) >= float(cond.get('valor', 0))
        except (TypeError, ValueError):
            return False
    if operador == 'menor_que':
        try:
            return float(valor_atual or 0) < float(cond.get('valor', 0))
        except (TypeError, ValueError):
            return False
    if operador == 'entre':
        try:
            return float(cond.get('valor_de', 0)) <= float(valor_atual or 0) <= float(cond.get('valor_ate', 0))
        except (TypeError, ValueError):
            return False
    logger.warning(f"[GATILHO] Operador desconhecido: '{operador}'")
    return False


def executar_acoes(gatilho, ticket):
    from apps.tickets.models import Status, Urgencia, Categoria, AcaoTicket, HistoricoTicket
    from django.contrib.auth import get_user_model
    User = get_user_model()
    acoes = gatilho.acoes or {}
    campos_alterados = []
    ticket._executando_gatilho = True
    try:
        status_id = acoes.get('alterar_status') or acoes.get('status')
        if status_id:
            try:
                ticket.status = Status.objects.get(pk=int(status_id))
                campos_alterados.append('status')
            except Exception as e:
                logger.error(f"[GATILHO/ACAO] alterar_status {status_id}: {e}")

        resp_id = acoes.get('alterar_responsavel') or acoes.get('responsavel')
        if resp_id:
            try:
                ticket.responsavel = User.objects.get(pk=int(resp_id))
                campos_alterados.append('responsavel')
            except Exception as e:
                logger.error(f"[GATILHO/ACAO] alterar_responsavel {resp_id}: {e}")

        urg_id = acoes.get('alterar_urgencia')
        if urg_id:
            try:
                ticket.urgencia = Urgencia.objects.get(pk=int(urg_id))
                campos_alterados.append('urgencia')
            except Exception as e:
                logger.error(f"[GATILHO/ACAO] alterar_urgencia {urg_id}: {e}")

        cat_id = acoes.get('alterar_categoria')
        if cat_id:
            try:
                ticket.categoria = Categoria.objects.get(pk=int(cat_id))
                campos_alterados.append('categoria')
            except Exception as e:
                logger.error(f"[GATILHO/ACAO] alterar_categoria {cat_id}: {e}")

        if campos_alterados:
            update_fields = [f for f in campos_alterados if f in ['status', 'responsavel', 'urgencia', 'categoria']]
            if update_fields:
                ticket.save(update_fields=update_fields)

        texto_nota = acoes.get('adicionar_nota') or acoes.get('adicionar_acao')
        if texto_nota:
            AcaoTicket.objects.create(
                ticket=ticket, tipo='interna', autor=ticket.cliente,
                conteudo=f"[GATILHO: {gatilho.nome}] {texto_nota}",
            )

        nova_tag = acoes.get('adicionar_tag')
        if nova_tag:
            tags = list(ticket.tags or [])
            if nova_tag not in tags:
                tags.append(nova_tag)
                ticket.tags = tags
                ticket.save(update_fields=['tags'])

        config_email = acoes.get('enviar_email')
        if config_email:
            _enviar_email_gatilho(ticket, gatilho, config_email)

        if campos_alterados:
            HistoricoTicket.objects.create(
                ticket=ticket, usuario=ticket.cliente,
                campo='gatilho_executado',
                valor_novo=f"Gatilho '{gatilho.nome}': {', '.join(campos_alterados)}"
            )
    finally:
        ticket._executando_gatilho = False


def _enviar_email_gatilho(ticket, gatilho, config_email):
    from django.core.mail import send_mail
    from django.conf import settings
    try:
        if isinstance(config_email, dict):
            assunto_tmpl = config_email.get('assunto', f'[Ticket #{ticket.numero}] {ticket.assunto}')
            corpo_tmpl = config_email.get('corpo', '')
            destinatarios_cfg = config_email.get('destinatarios', ['solicitante'])
        else:
            assunto_tmpl = f'[Ticket #{ticket.numero}] {ticket.assunto}'
            corpo_tmpl = ''
            destinatarios_cfg = [str(config_email)] if config_email else ['solicitante']

        variaveis = {
            '{ticket.id}': ticket.numero,
            '{ticket.numero}': ticket.numero,
            '{ticket.assunto}': ticket.assunto or '',
            '{ticket.status}': ticket.status.nome if ticket.status else '',
            '{ticket.creator.name}': ticket.solicitante.get_full_name() or ticket.solicitante.username if ticket.solicitante else '',
            '{ticket.solicitante}': ticket.solicitante.get_full_name() or ticket.solicitante.username if ticket.solicitante else '',
            '{ticket.responsavel}': ticket.responsavel.get_full_name() or ticket.responsavel.username if ticket.responsavel else 'Não atribuído',
            '{ticket.urgencia}': ticket.urgencia.nome if ticket.urgencia else '',
            '{ticket.categoria}': ticket.categoria.nome if ticket.categoria else '',
            '{ticket.previsao_solucao}': ticket.previsao_solucao.strftime(
                '%d/%m/%Y %H:%M') if ticket.previsao_solucao else '',
            '{gatilho.nome}': gatilho.nome,
        }
        assunto = assunto_tmpl
        corpo = corpo_tmpl
        for var, val in variaveis.items():
            assunto = assunto.replace(var, str(val))
            corpo = corpo.replace(var, str(val))

        emails = _resolver_destinatarios(destinatarios_cfg, ticket)
        if not emails:
            return
        send_mail(assunto, corpo, getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@sistema.com'), emails,
                  fail_silently=True)
        logger.info(f"[GATILHO/EMAIL] Enviado para {emails} — Ticket #{ticket.numero}")
    except Exception as e:
        logger.error(f"[GATILHO/EMAIL] Erro no gatilho '{gatilho.nome}': {e}")


def _resolver_destinatarios(destinatarios_cfg, ticket):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    emails = set()
    for dest in destinatarios_cfg:
        if dest in ('solicitante', 'gerador') and ticket.solicitante and ticket.solicitante.email:
            emails.add(ticket.solicitante.email)
        elif dest == 'responsavel' and ticket.responsavel and ticket.responsavel.email:
            emails.add(ticket.responsavel.email)
        elif dest == 'todos_agentes':
            for a in User.objects.filter(cliente=ticket.cliente, is_staff=True, is_active=True).exclude(email=''):
                emails.add(a.email)
        elif '@' in str(dest):
            emails.add(dest)
        else:
            try:
                u = User.objects.get(pk=int(dest))
                if u.email:
                    emails.add(u.email)
            except Exception:
                pass
    return list(emails)


# ─── Funções de notificação (adicionar ao signals.py existente) ──────────────

def notificar(usuario, ticket, tipo, titulo, mensagem=''):
    """Cria uma notificação in-app de forma segura."""
    if not usuario or not usuario.pk:
        return
    try:
        from apps.tickets.models import NotificacaoTicket
        NotificacaoTicket.objects.create(
            usuario=usuario,
            ticket=ticket,
            tipo=tipo,
            titulo=titulo,
            mensagem=mensagem,
        )
    except Exception as e:
        logger.error(f"[NOTIF] Erro ao criar notificação: {e}")


def notificar_ticket_criado(ticket):
    """Notifica responsável / equipe quando ticket é criado."""
    # Notifica responsável se já atribuído
    if ticket.responsavel:
        notificar(
            ticket.responsavel, ticket,
            'atribuido',
            f'Ticket #{ticket.numero} atribuído a você',
            f'Assunto: {ticket.assunto}'
        )
    # Notifica agentes da equipe
    if hasattr(ticket, 'equipe') and ticket.equipe:
        for agente in ticket.equipe.agentes.filter(is_active=True):
            if agente != ticket.responsavel:
                notificar(
                    agente, ticket,
                    'ticket_criado',
                    f'Novo ticket #{ticket.numero} na equipe {ticket.equipe.nome}',
                    f'Assunto: {ticket.assunto}'
                )


def notificar_nova_acao(acao):
    """Notifica partes envolvidas quando uma nova ação pública é adicionada."""
    ticket = acao.ticket
    autor = acao.autor

    # Notifica responsável (se não é o autor)
    if ticket.responsavel and ticket.responsavel != autor:
        notificar(
            ticket.responsavel, ticket,
            'nova_acao',
            f'Nova resposta no ticket #{ticket.numero}',
            f'Por: {autor.get_full_name() or autor.username}'
        )

    # Notifica solicitante (se não é o autor e a ação é pública)
    if acao.tipo == 'publica' and ticket.solicitante and ticket.solicitante != autor:
        notificar(
            ticket.solicitante, ticket,
            'nova_acao',
            f'Resposta no seu ticket #{ticket.numero}',
            f'Por: {autor.get_full_name() or autor.username}'
        )


def notificar_status_alterado(ticket, status_anterior):
    """Notifica quando o status de um ticket muda."""
    # Notifica solicitante
    if ticket.solicitante:
        notificar(
            ticket.solicitante, ticket,
            'status_alterado',
            f'Status do ticket #{ticket.numero} alterado',
            f'De: {status_anterior} → Para: {ticket.status.nome}'
        )

    # Notifica responsável (se não foi ele quem alterou — não temos o usuário aqui,
    # então notificamos sempre)
    if ticket.responsavel and ticket.responsavel != ticket.solicitante:
        notificar(
            ticket.responsavel, ticket,
            'status_alterado',
            f'Status do ticket #{ticket.numero} alterado para {ticket.status.nome}',
            ''
        )