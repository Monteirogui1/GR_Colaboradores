from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db.models import Count
from apps.tickets.models import Ticket, StatusBase
from apps.ativos.models import Ativo
from apps.inventory.models import Machine


@login_required
def dashboard_view(request):
    """Dashboard principal da aplicação"""
    user = request.user
    cliente = user if user.is_staff else user

    hoje = timezone.now().date()
    inicio_mes = hoje.replace(day=1)

    context = {
        'stats': {}
    }

    # ==================== TICKETS ====================
    try:
        

        tickets_query = Ticket.objects.all()

        context['stats']['tickets'] = {
            'total_abertos': tickets_query.exclude(
                status__status_base__in=[StatusBase.FECHADO, StatusBase.CANCELADO]
            ).count(),
            'abertos_hoje': tickets_query.filter(criado_em__date=hoje).count(),
            'vencidos': tickets_query.filter(
                previsao_solucao__lt=timezone.now()
            ).exclude(
                status__status_base__in=[StatusBase.FECHADO, StatusBase.CANCELADO, StatusBase.RESOLVIDO]
            ).count(),
            'resolvidos_mes': tickets_query.filter(
                resolvido_em__gte=inicio_mes,
                status__status_base=StatusBase.RESOLVIDO
            ).count(),
        }

        # Tickets por status
        context['tickets_por_status'] = tickets_query.values(
            'status__nome', 'status__cor'
        ).annotate(
            total=Count('id')
        ).order_by('-total')[:5]

        # Tickets por categoria
        context['tickets_por_categoria'] = tickets_query.values(
            'categoria__nome'
        ).annotate(
            total=Count('id')
        ).order_by('-total')[:5]

        # Tickets recentes
        context['tickets_recentes'] = tickets_query.select_related(
            'solicitante', 'status', 'categoria', 'urgencia'
        ).order_by('-criado_em')[:10]

        # Meus tickets (se for agente)
        if user.is_staff:
            context['stats']['tickets']['meus_tickets'] = tickets_query.filter(
                responsavel=user
            ).exclude(
                status__status_base__in=[StatusBase.FECHADO, StatusBase.CANCELADO]
            ).count()

        context['has_tickets'] = True
    except (ImportError, Exception) as e:
        context['has_tickets'] = False
        context['stats']['tickets'] = {
            'total_abertos': 0,
            'abertos_hoje': 0,
            'vencidos': 0,
            'resolvidos_mes': 0,
        }

    # ==================== ATIVOS ====================
    try:
        

        ativos_query = Ativo.objects.all()

        context['stats']['ativos'] = {
            'total': ativos_query.count(),
            'ativos': ativos_query.filter(
                status__nome__icontains='ativo'
            ).count(),
            'manutencao': ativos_query.filter(
                status__nome__icontains='manutenção'
            ).count(),
            'inativos': ativos_query.filter(
                status__nome__icontains='inativo'
            ).count(),
        }

        # Ativos por categoria
        context['ativos_por_categoria'] = ativos_query.values(
            'categoria__nome'
        ).annotate(
            total=Count('id')
        ).order_by('-total')[:5]

        # Ativos por localização
        context['ativos_por_localizacao'] = ativos_query.values(
            'localizacao__nome'
        ).annotate(
            total=Count('id')
        ).order_by('-total')[:5]

        context['has_ativos'] = True
    except (ImportError, Exception) as e:
        context['has_ativos'] = False
        context['stats']['ativos'] = {
            'total': 0,
            'ativos': 0,
            'manutencao': 0,
            'inativos': 0,
        }

    # ==================== MÁQUINAS ====================
    try:
        

        maquinas_query = Machine.objects.all()

        context['stats']['maquinas'] = {
            'total': maquinas_query.count(),
            'online': maquinas_query.filter(is_online=True).count(),
            'offline': maquinas_query.filter(is_online=False).count(),
        }

        # Máquinas por grupo
        context['maquinas_por_grupo'] = maquinas_query.values(
            'group__name'
        ).annotate(
            total=Count('id')
        ).order_by('-total')[:5]

        # Máquinas recentes
        context['maquinas_recentes'] = maquinas_query.order_by('-last_seen')[:5]

        context['has_maquinas'] = True
    except (ImportError, Exception) as e:
        context['has_maquinas'] = False
        context['stats']['maquinas'] = {
            'total': 0,
            'online': 0,
            'offline': 0,
        }

    # ==================== AUDITORIAS ====================
    try:
        from apps.auditoria.models import Auditoria

        auditorias_query = Auditoria.objects.all()

        context['stats']['auditorias'] = {
            'total': auditorias_query.count(),
            'em_andamento': auditorias_query.filter(status='em_andamento').count(),
            'concluidas': auditorias_query.filter(status='concluida').count(),
        }

        # Auditorias recentes
        context['auditorias_recentes'] = auditorias_query.order_by('-data_criacao')[:5]

        context['has_auditorias'] = True
    except (ImportError, Exception) as e:
        context['has_auditorias'] = False
        context['stats']['auditorias'] = {
            'total': 0,
            'em_andamento': 0,
            'concluidas': 0,
        }

    return render(request, 'home/dashboard.html', context)