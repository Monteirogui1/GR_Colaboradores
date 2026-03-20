from .models import Notification, Machine
import logging
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.utils import timezone
from django.conf import settings
from datetime import timedelta


logger = logging.getLogger(__name__)


@receiver(post_save, sender=Notification)
def notification_created(sender, instance, created, **kwargs):
    """Signal executado após criar/atualizar uma notificação"""
    if created:
        # Notificação foi criada
        print(f"Nova notificação criada: {instance.title}")
    else:
        # Notificação foi atualizada
        if instance.is_read:
            print(f"Notificação marcada como lida: {instance.title}")


@receiver(post_save, sender=Machine)
def update_machine_online_status(sender, instance, **kwargs):
    instance.update_online_status()