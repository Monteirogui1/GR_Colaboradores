from django.apps import AppConfig


class NotificacaoConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.notificacao'

    def ready(self):
        import apps.notificacao.signals