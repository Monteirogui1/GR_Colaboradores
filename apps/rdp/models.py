import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.inventory.models import AgentToken, Machine


class RDPMachinePolicy(models.Model):
    MODE_AUTO = "auto"
    MODE_P2P_ONLY = "p2p_only"
    MODE_RELAY_ONLY = "relay_only"
    CONNECTION_MODE_CHOICES = [
        (MODE_AUTO, "Auto (P2P com fallback)"),
        (MODE_P2P_ONLY, "Somente P2P"),
        (MODE_RELAY_ONLY, "Somente Relay"),
    ]

    QUALITY_AUTO = "auto"
    QUALITY_HIGH = "high"
    QUALITY_MEDIUM = "medium"
    QUALITY_LOW = "low"
    DEFAULT_QUALITY_CHOICES = [
        (QUALITY_AUTO, "Auto"),
        (QUALITY_HIGH, "High"),
        (QUALITY_MEDIUM, "Medium"),
        (QUALITY_LOW, "Low"),
    ]

    machine = models.OneToOneField(
        Machine,
        on_delete=models.CASCADE,
        related_name="rdp_policy",
        verbose_name="Máquina",
    )
    connection_mode = models.CharField(
        max_length=20,
        choices=CONNECTION_MODE_CHOICES,
        default=MODE_AUTO,
        verbose_name="Modo de conexão",
    )
    default_quality = models.CharField(
        max_length=10,
        choices=DEFAULT_QUALITY_CHOICES,
        default=QUALITY_AUTO,
        verbose_name="Qualidade padrão",
    )
    allow_elevated_input = models.BooleanField(default=True)
    require_justification = models.BooleanField(default=True)
    silent_access_only = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Política RDP por Máquina"
        verbose_name_plural = "Políticas RDP por Máquina"

    def __str__(self) -> str:
        return f"{self.machine.hostname} ({self.connection_mode})"


class RDPSessionToken(models.Model):
    machine = models.ForeignKey(
        Machine,
        on_delete=models.CASCADE,
        related_name="rdp_session_tokens",
        verbose_name="Máquina",
    )
    agent_token = models.ForeignKey(
        AgentToken,
        on_delete=models.PROTECT,
        related_name="rdp_session_tokens",
        verbose_name="Token de agente",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="rdp_session_tokens",
        verbose_name="Criado por",
    )
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    reason = models.CharField(max_length=255, blank=True, default="")
    requested_mode = models.CharField(max_length=20, default=RDPMachinePolicy.MODE_AUTO)
    requested_quality = models.CharField(max_length=10, default=RDPMachinePolicy.QUALITY_AUTO)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Token de Sessão RDP"
        verbose_name_plural = "Tokens de Sessão RDP"

    @classmethod
    def issue(
        cls,
        *,
        machine: Machine,
        agent_token: AgentToken,
        user,
        ttl_seconds: int,
        reason: str = "",
        requested_mode: str = RDPMachinePolicy.MODE_AUTO,
        requested_quality: str = RDPMachinePolicy.QUALITY_AUTO,
    ) -> tuple[str, "RDPSessionToken"]:
        raw = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        obj = cls.objects.create(
            machine=machine,
            agent_token=agent_token,
            created_by=user,
            token_hash=token_hash,
            expires_at=timezone.now() + timedelta(seconds=max(30, ttl_seconds)),
            reason=(reason or "")[:255],
            requested_mode=requested_mode or RDPMachinePolicy.MODE_AUTO,
            requested_quality=requested_quality or RDPMachinePolicy.QUALITY_AUTO,
        )
        return raw, obj

    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at


class RDPSessionAudit(models.Model):
    EVENT_TOKEN_ISSUED = "token_issued"
    EVENT_SESSION_STARTED = "session_started"
    EVENT_SESSION_CLOSED = "session_closed"
    EVENT_CHOICES = [
        (EVENT_TOKEN_ISSUED, "Token emitido"),
        (EVENT_SESSION_STARTED, "Sessão iniciada"),
        (EVENT_SESSION_CLOSED, "Sessão encerrada"),
    ]

    event_type = models.CharField(max_length=32, choices=EVENT_CHOICES)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="rdp_audit_events")
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, related_name="rdp_audit_events")
    session_token = models.ForeignKey(
        RDPSessionToken,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    session_id = models.CharField(max_length=64, blank=True, default="")
    reason = models.CharField(max_length=255, blank=True, default="")
    connection_mode = models.CharField(max_length=20, blank=True, default=RDPMachinePolicy.MODE_AUTO)
    client_ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Auditoria de Sessão RDP"
        verbose_name_plural = "Auditoria de Sessões RDP"
