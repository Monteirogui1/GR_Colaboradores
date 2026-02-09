from django.urls import path
from django.conf.urls.static import static

from .views import MarcarNotificacaoLidaView

app_name = 'notificacao'

urlpatterns = [
    path('notificacao/<int:notificacao_id>/lida/', MarcarNotificacaoLidaView.as_view(), name='marcar_notificacao_lida'),
]