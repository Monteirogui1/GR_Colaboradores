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
    install_date    = models.CharField("Instalação SO", max_length=30, null=True, blank=True)
    last_boot       = models.CharField("Último Boot", max_length=30, null=True, blank=True)
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

    last_seen = models.DateTimeField("Última Conexão", auto_now=True)
    is_online = models.BooleanField("Online", default=False)
    group     = models.ForeignKey(MachineGroup, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return self.hostname

    class Meta:
        verbose_name = "Máquina"
        verbose_name_plural = "Máquinas"


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
    title = models.CharField("Título", max_length=200)
    message = models.TextField("Mensagem")
    created_at = models.DateTimeField("Criado em", auto_now_add=True)
    sent_to_all = models.BooleanField("Enviar para todos", default=True)
    machines = models.ManyToManyField(Machine, blank=True, verbose_name="Máquinas Específicas")
    groups = models.ManyToManyField(MachineGroup, blank=True, verbose_name="Grupos")

    def __str__(self):
        return self.title

    class Meta:
        verbose_name = "Notificação"
        verbose_name_plural = "Notificações"


class AgentToken(models.Model):
    """Token de instalação do agente"""

    token = models.CharField(max_length=8, unique=True, verbose_name="Token")
    token_hash = models.CharField(max_length=64, unique=True, verbose_name="Hash do Token")
    machine_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Nome da Máquina"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='created_tokens',
        verbose_name="Criado por"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    used_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Usado em"
    )
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

    def mark_as_used(self, machine_name):
        """Marca token como usado"""
        self.used_at = timezone.now()
        self.machine_name = machine_name
        self.save()

    def get_status_display(self):
        """Retorna o status do token para exibição"""
        if not self.is_active:
            return {'text': 'Inativo', 'class': 'secondary'}
        elif self.is_expired():
            return {'text': 'Expirado', 'class': 'warning'}
        elif self.used_at:
            return {'text': 'Usado', 'class': 'info'}
        else:
            return {'text': 'Disponível', 'class': 'success'}


class AgentVersion(models.Model):
    """Versões do agente disponíveis"""

    version = models.CharField(max_length=20, unique=True, verbose_name="Versão")
    file_path = models.FileField(
        upload_to='agent_versions/',
        verbose_name="Arquivo"
    )
    release_notes = models.TextField(verbose_name="Notas de Lançamento")
    is_active = models.BooleanField(default=True, verbose_name="Ativo")
    is_mandatory = models.BooleanField(
        default=False,
        verbose_name="Atualização Obrigatória"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        verbose_name="Criado por"
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Versão do Agente"
        verbose_name_plural = "Versões do Agente"
        

    def __str__(self):
        return f"Versão {self.version}"

    def get_status_display(self):
        """Retorna o status da versão para exibição"""
        if self.is_active:
            if self.is_mandatory:
                return {'text': 'Ativa (Obrigatória)', 'class': 'danger'}
            return {'text': 'Ativa', 'class': 'success'}
        return {'text': 'Inativa', 'class': 'secondary'}