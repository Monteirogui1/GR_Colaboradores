from .models import Notification, Machine
import logging
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.utils import timezone
from django.conf import settings
from datetime import timedelta


logger = logging.getLogger(__name__)


# Configurações de timeout (minutos sem atualização para considerar offline)
MACHINE_OFFLINE_TIMEOUT = getattr(settings, 'MACHINE_OFFLINE_TIMEOUT', 15)

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


@receiver(pre_save, sender=Machine)
def verificar_status_maquina(sender, instance, **kwargs):
    """
    Verifica automaticamente se a máquina deve ser marcada como offline
    baseado no tempo desde a última atualização (last_seen)

    Executa antes de salvar a máquina
    """
    if not instance.pk:
        # Máquina nova - marcar como online por padrão
        instance.is_online = True
        return

    try:
        # Buscar estado anterior da máquina
        old_instance = sender.objects.get(pk=instance.pk)

        # Se last_seen mudou, a máquina acabou de reportar status
        if instance.last_seen != old_instance.last_seen:
            # Máquina acabou de se comunicar - marcar como ONLINE
            instance.is_online = True
            return

        # Se last_seen NÃO mudou, verificar se passou do timeout
        if instance.last_seen:
            # Calcular o threshold de timeout
            timeout_threshold = timezone.now() - timedelta(minutes=MACHINE_OFFLINE_TIMEOUT)

            if instance.last_seen < timeout_threshold:
                # Passou do timeout - marcar como OFFLINE
                instance.is_online = False
            else:
                # Ainda dentro do prazo - manter ONLINE
                instance.is_online = True
        else:
            # Sem last_seen - considerar offline
            instance.is_online = False

    except sender.DoesNotExist:
        # Máquina nova
        instance.is_online = True