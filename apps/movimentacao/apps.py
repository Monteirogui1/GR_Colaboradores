from django.apps import AppConfig


class MovimentacaoConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.movimentacao'

    def ready(self):
        import apps.movimentacao.signals
