from .models import Notificacao

def notificacoes(request):
    return {
        'notificacoes': Notificacao.objects.filter(lida=False)
    }
