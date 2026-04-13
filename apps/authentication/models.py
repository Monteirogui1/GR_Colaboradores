from django.db import models
from django.contrib.auth.models import AbstractUser
from apps.shared.models import Cliente

class User(AbstractUser):
    assinatura = models.TextField(
        "Assinatura",
        blank=True,
        help_text="HTML da assinatura exibida automaticamente no editor de resposta"
    )
    cliente = models.ForeignKey(
        'shared.Cliente',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='usuarios'
    )
