from django.apps import AppConfig


class AtivosConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.ativos'

    def ready(self):
        import apps.ativos.signals
