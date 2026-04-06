from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Fecha automaticamente tickets resolvidos há mais de N dias"

    def add_arguments(self, parser):
        parser.add_argument("--dias", type=int, default=7)

    def handle(self, *args, **options):
        from apps.tickets.tasks import fechar_tickets_resolvidos
        result = fechar_tickets_resolvidos(dias=options["dias"])
        self.stdout.write(self.style.SUCCESS(f"Fechamento: {result}"))