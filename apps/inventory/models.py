from django.utils import timezone
from django.db import models
from django.conf import settings
import secrets
import string
import hashlib
from datetime import datetime
from django.contrib.postgres.fields import JSONField


class MachineGroup(models.Model):
    name = models.CharField("Nome do Grupo", max_length=100)
    description = models.TextField("Descrição", blank=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Grupo de Máquinas"
        verbose_name_plural = "Grupos de Máquinas"


class Machine(models.Model):
    loggedUser = models.CharField("loggedUser", max_length=200, null=True, blank=True)
    hostname        = models.CharField("Hostname", max_length=100, unique=True)
    ip_address      = models.GenericIPAddressField("IP")
    mac_address     = models.CharField("MAC Address", max_length=17, null=True, blank=True)
    os_version      = models.CharField("Versão do SO", max_length=100, null=True, blank=True)
    tpm = models.JSONField("TpmInfo", null=True, blank=True)

    # RAM slots
    total_memory_slots = models.IntegerField("Slots Totais", null=True, blank=True)
    populated_memory_slots = models.IntegerField("Slots Ocupados", null=True, blank=True)
    memory_modules = models.JSONField("Módulos de Memória", null=True, blank=True)

    manufacturer    = models.CharField("Fabricante", max_length=100, null=True, blank=True)
    model           = models.CharField("Modelo", max_length=100, null=True, blank=True)
    serial_number   = models.CharField("Serial BIOS", max_length=100, null=True, blank=True)
    bios_version    = models.CharField("Versão BIOS", max_length=100, null=True, blank=True)
    bios_release    = models.CharField("Data BIOS", max_length=50, null=True, blank=True)
    os_caption      = models.CharField("SO Caption", max_length=200, null=True, blank=True)
    os_architecture = models.CharField("Arquitetura SO", max_length=50, null=True, blank=True)
    os_build        = models.CharField("Build SO", max_length=20, null=True, blank=True)
    install_date    = models.CharField("Instalação SO", max_length=50, null=True, blank=True)
    last_boot       = models.CharField("Último Boot", max_length=50, null=True, blank=True)
    uptime_days     = models.FloatField("Uptime (dias)", null=True, blank=True)

    cpu             = models.CharField("CPU", max_length=200, null=True, blank=True)
    ram_gb          = models.FloatField("RAM (GB)", null=True, blank=True)
    disk_space_gb   = models.FloatField("Disco Total (GB)", null=True, blank=True)
    disk_free_gb    = models.FloatField("Disco Livre (GB)", null=True, blank=True)

    network_info    = models.JSONField("Adaptadores Rede", null=True, blank=True)
    gpu_name        = models.CharField("Placa de Vídeo", max_length=200, null=True, blank=True)
    gpu_driver      = models.CharField("Driver Vídeo", max_length=100, null=True, blank=True)
    antivirus_name  = models.CharField("Antivírus", max_length=200, null=True, blank=True)
    av_state        = models.CharField("Estado AV", max_length=50, null=True, blank=True)

    last_seen = models.DateTimeField("Última Conexão", null=True, blank=True)
    is_online = models.BooleanField("Online", default=False)
    group     = models.ForeignKey(MachineGroup, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return self.hostname

    class Meta:
        verbose_name = "Máquina"
        verbose_name_plural = "Máquinas"

    def update_online_status(self):
        new_status = self.is_currently_online
        if self.is_online != new_status:
            self.is_online = new_status
            self.save(update_fields=['is_online'])

    @property
    def is_currently_online(self) -> bool:
        """Calcula status em tempo real, sem depender do campo is_online."""
        if not self.last_seen:
            return False
        timeout = getattr(settings, 'MACHINE_OFFLINE_TIMEOUT', 15)
        return (timezone.now() - self.last_seen).total_seconds() < timeout * 60


class BlockedSite(models.Model):
    url = models.CharField("URL Bloqueada", max_length=255)
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Máquina")
    group = models.ForeignKey(MachineGroup, on_delete=models.CASCADE, null=True, blank=True, verbose_name="Grupo")

    class Meta:
        unique_together = (('url', 'machine'), ('url', 'group'))
        verbose_name = "Site Bloqueado"
        verbose_name_plural = "Sites Bloqueados"

    def __str__(self):
        target = self.machine or self.group
        return f"{self.url} → {target}"


class Notification(models.Model):
    """
    Notificação para ser exibida no agente da máquina cliente

    Campos:
        - machine: Máquina que receberá a notificação
        - title: Título da notificação
        - message: Mensagem/conteúdo da notificação
        - type: Tipo de notificação (info, success, warning, error, alert, critical)
        - priority: Prioridade (low, normal, high, critical)
        - status: Status da notificação (pending, read, expired)
        - is_read: Flag booleana se foi lida
        - created_at: Data de criação
        - updated_at: Data de última atualização
        - read_at: Data em que foi lida
        - expires_at: Data de expiração (opcional)
    """

    # Choices para tipo de notificação
    TYPE_CHOICES = [
        ('info', 'Informação'),
        ('success', 'Sucesso'),
        ('warning', 'Aviso'),
        ('error', 'Erro'),
        ('alert', 'Alerta'),
        ('critical', 'Crítico'),
    ]

    # Choices para prioridade
    PRIORITY_CHOICES = [
        ('low', 'Baixa'),
        ('normal', 'Normal'),
        ('high', 'Alta'),
        ('critical', 'Crítica'),
    ]

    # Choices para status
    STATUS_CHOICES = [
        ('pending', 'Pendente'),
        ('read', 'Lida'),
        ('expired', 'Expirada'),
    ]

    # Relacionamento com a máquina
    machine = models.ForeignKey(
        'Machine',
        on_delete=models.CASCADE,
        related_name='notifications',
        verbose_name='Máquina',
        help_text='Máquina que receberá a notificação'
    )

    # Conteúdo da notificação
    title = models.CharField(
        max_length=200,
        verbose_name='Título',
        help_text='Título da notificação (máximo 200 caracteres)'
    )

    message = models.TextField(
        verbose_name='Mensagem',
        help_text='Conteúdo detalhado da notificação'
    )

    # Tipo e prioridade
    type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default='info',
        verbose_name='Tipo',
        help_text='Tipo de notificação (define ícone e cor)'
    )

    priority = models.CharField(
        max_length=20,
        choices=PRIORITY_CHOICES,
        default='normal',
        verbose_name='Prioridade',
        help_text='Prioridade da notificação'
    )

    # Status e controle
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        verbose_name='Status',
        help_text='Status atual da notificação'
    )

    is_read = models.BooleanField(
        default=False,
        verbose_name='Lida',
        help_text='Indica se a notificação já foi lida pelo usuário'
    )

    # Timestamps
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Criada em',
        help_text='Data e hora de criação da notificação'
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Atualizada em',
        null=True,
        blank=True,
        help_text='Data e hora da última atualização'
    )

    read_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Lida em',
        help_text='Data e hora em que foi lida pelo usuário'
    )

    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Expira em',
        help_text='Data e hora de expiração (opcional)'
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Notificação'
        verbose_name_plural = 'Notificações'

    def __str__(self):
        return f'{self.machine.hostname} - {self.title}'

    def mark_as_read(self):
        """
        Marca a notificação como lida

        Atualiza:
            - is_read = True
            - status = 'read'
            - read_at = agora
        """
        self.is_read = True
        self.status = 'read'
        self.read_at = timezone.now()
        self.save(update_fields=['is_read', 'status', 'read_at'])

    def is_expired(self):
        """
        Verifica se a notificação está expirada

        Returns:
            bool: True se expirada, False caso contrário
        """
        if self.expires_at:
            return timezone.now() > self.expires_at
        return False

    def mark_as_expired(self):
        """Marca a notificação como expirada"""
        self.status = 'expired'
        self.save(update_fields=['status'])

    @property
    def age_in_hours(self):
        """
        Retorna a idade da notificação em horas

        Returns:
            float: Número de horas desde a criação
        """
        delta = timezone.now() - self.created_at
        return delta.total_seconds() / 3600

    @property
    def is_urgent(self):
        """
        Verifica se a notificação é urgente

        Returns:
            bool: True se prioridade é high ou critical
        """
        return self.priority in ['high', 'critical']

    def save(self, *args, **kwargs):
        """
        Override do save para lógica adicional

        - Se expirada, muda status automaticamente
        - Se marcada como lida, atualiza read_at
        """
        # Verificar expiração
        if self.expires_at and timezone.now() > self.expires_at:
            self.status = 'expired'

        # Se foi marcada como lida mas não tem read_at, adicionar
        if self.is_read and not self.read_at:
            self.read_at = timezone.now()
            self.status = 'read'

        super().save(*args, **kwargs)


class AgentToken(models.Model):
    """Token de instalação do agente"""

    token = models.CharField(max_length=8, unique=True, verbose_name="Token")
    token_hash = models.CharField(max_length=64, unique=True, verbose_name="Hash do Token")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='created_tokens',
        verbose_name="Criado por"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    is_active = models.BooleanField(default=True, verbose_name="Ativo")
    expires_at = models.DateTimeField(verbose_name="Expira em")

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Token do Agente"
        verbose_name_plural = "Tokens do Agente"
        db_table = 'inventory_agent_token'

    def __str__(self):
        return f"Token {self.token} - {self.created_at.strftime('%Y-%m-%d')}"

    @staticmethod
    def generate_token():
        """Gera token de 8 caracteres com números, letras e especiais"""
        uppercase = string.ascii_uppercase
        lowercase = string.ascii_lowercase
        digits = string.digits
        special = "!@#$%&*"

        # Garante pelo menos 1 de cada tipo
        token_chars = [
            secrets.choice(uppercase),
            secrets.choice(lowercase),
            secrets.choice(digits),
            secrets.choice(special)
        ]

        # Completa com caracteres aleatórios
        all_chars = uppercase + lowercase + digits + special
        token_chars.extend(secrets.choice(all_chars) for _ in range(4))

        # Embaralha
        token = list(token_chars)
        secrets.SystemRandom().shuffle(token)

        return ''.join(token)

    @staticmethod
    def hash_token(token):
        """Cria hash do token"""
        return hashlib.sha256(token.encode()).hexdigest()

    def is_expired(self):
        """Verifica se o token expirou"""
        now = timezone.now()
        # Garante que ambos são timezone-aware para comparação
        if timezone.is_naive(self.expires_at):
            # Se expires_at é naive, torna timezone-aware
            expires_at = timezone.make_aware(self.expires_at)
        else:
            expires_at = self.expires_at

        return now > expires_at

    def mark_as_used(self, machine_name: str) -> None:
        """
        Registra (ou atualiza) o uso deste token em uma máquina.
        Substituiu o campo único machine_name/used_at por AgentTokenUsage,
        permitindo que um token seja usado em várias máquinas.
        """
        AgentTokenUsage.objects.update_or_create(
            agent_token=self,
            machine_name=machine_name,
        )

    def get_status_display(self) -> dict:
        """
        Retorna o status do token para exibição no template.

        Ordem de avaliação:
          1. Inativo   — is_active=False
          2. Expirado  — passou da expires_at
          3. Em uso    — tem pelo menos um AgentTokenUsage
          4. Disponível — nunca usado
        """
        if not self.is_active:
            return {'text': 'Inativo', 'class': 'secondary'}
        if self.is_expired():
            return {'text': 'Expirado', 'class': 'warning'}
        # usa prefetch quando disponível, senão faz query
        try:
            # se a view fez prefetch_related('usages'), usages.all() não gera query extra
            has_usage = self.usages.exists()
        except Exception:
            has_usage = False
        if has_usage:
            count = self.usages.count()
            label = f'Em uso ({count} máquina{"s" if count != 1 else ""})'
            return {'text': label, 'class': 'info'}
        return {'text': 'Disponível', 'class': 'success'}

class AgentTokenUsage(models.Model):
    agent_token = models.ForeignKey(
        AgentToken,
        on_delete=models.CASCADE,
        related_name='usages',
        verbose_name='Token'
    )
    machine_name = models.CharField(max_length=255, verbose_name='Nome da Máquina')
    first_used_at = models.DateTimeField(auto_now_add=True, verbose_name='Primeiro uso')
    last_used_at = models.DateTimeField(auto_now=True, verbose_name='Último uso')

    class Meta:
        verbose_name = 'Uso do Token'
        verbose_name_plural = 'Usos do Token'
        unique_together = ('agent_token', 'machine_name')

    def __str__(self):
        return f'{self.agent_token.token} - {self.machine_name}'


class AgentVersion(models.Model):
    """
    Versão publicada de um agente (service ou tray).

    Constraints:
        - unique_together('version', 'agent_type') — permite mesma versão
          numérica para tipos distintos (ex: 3.2.0/service e 3.2.0/tray).
        - SHA-256 calculado automaticamente no save() quando o arquivo muda.
    """

    AGENT_TYPE_CHOICES = [
        ("service", "Agent Service (agent_service.exe)"),
        ("tray",    "Agent Tray (agent_tray.exe)"),
    ]

    version = models.CharField(max_length=20, verbose_name="Versão")
    agent_type = models.CharField(
        max_length=10,
        choices=AGENT_TYPE_CHOICES,
        default="service",
        verbose_name="Tipo de Agente",
    )
    file_path = models.FileField(upload_to="agent_versions/", verbose_name="Arquivo")
    sha256 = models.CharField(
        max_length=64,
        blank=True,
        verbose_name="SHA-256 do arquivo",
        help_text="Preenchido automaticamente ao salvar",
    )
    release_notes = models.TextField(verbose_name="Notas de Lançamento")
    is_active = models.BooleanField(default=True, verbose_name="Ativo")
    is_mandatory = models.BooleanField(default=False, verbose_name="Atualização Obrigatória")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        verbose_name="Criado por",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Versão do Agente"
        verbose_name_plural = "Versões do Agente"
        unique_together = (("version", "agent_type"),)  # FIX: era unique=True só em version

    def __str__(self) -> str:
        return f"{self.get_agent_type_display()} v{self.version}"

    def save(self, *args, **kwargs) -> None:
        """Recalcula SHA-256 sempre que o arquivo for substituído."""
        if self.file_path and hasattr(self.file_path, "file"):
            self.file_path.seek(0)
            self.sha256 = hashlib.sha256(self.file_path.read()).hexdigest()
            self.file_path.seek(0)
        super().save(*args, **kwargs)

    @staticmethod
    def version_tuple(v: str) -> tuple:
        """Converte string semântica em tupla comparável."""
        try:
            return tuple(int(x) for x in str(v).split("."))
        except (ValueError, AttributeError):
            return (0, 0, 0)

    @classmethod
    def latest_active(cls, agent_type: str) -> "AgentVersion | None":
        """
        Retorna a versão ativa mais recente semanticamente para o tipo.

        Busca todas as ativas e ordena em Python — necessário porque
        ordenação semântica não é suportada nativamente em SQL para strings
        no formato MAJOR.MINOR.PATCH.
        """
        candidates = list(
            cls.objects.filter(is_active=True, agent_type=agent_type)
        )
        if not candidates:
            return None
        return max(candidates, key=lambda v: cls.version_tuple(v.version))


class AgentDownloadLog(models.Model):
    """
    Registro de cada download de binário do agente.

    Permite auditoria de qual máquina baixou qual versão e quando,
    sem expor dados sensíveis (não armazena token).
    """

    agent_version = models.ForeignKey(
        AgentVersion,
        on_delete=models.CASCADE,
        related_name="download_logs",
        verbose_name="Versão",
    )
    machine_name = models.CharField(max_length=255, verbose_name="Máquina")
    ip_address = models.GenericIPAddressField(
        null=True, blank=True, verbose_name="IP"
    )
    downloaded_at = models.DateTimeField(auto_now_add=True, verbose_name="Baixado em")

    class Meta:
        ordering = ["-downloaded_at"]
        verbose_name = "Log de Download"
        verbose_name_plural = "Logs de Download"

    def __str__(self) -> str:
        return f"{self.machine_name} → v{self.agent_version.version} em {self.downloaded_at:%d/%m/%Y %H:%M}"