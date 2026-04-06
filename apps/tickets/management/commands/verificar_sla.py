from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Verifica SLA dos tickets abertos e cria alertas"

    def handle(self, *args, **options):
        from apps.tickets.tasks import verificar_sla
        result = verificar_sla()
        self.stdout.write(self.style.SUCCESS(f"SLA verificado: {result}"))

            