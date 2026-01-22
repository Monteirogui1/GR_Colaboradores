from django.db import models
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
    loggedUser = models.CharField("loggedUser", max_length=200, blank=True)
    hostname        = models.CharField("Hostname", max_length=100, unique=True)
    ip_address      = models.GenericIPAddressField("IP")
    mac_address     = models.CharField("MAC Address", max_length=17, blank=True)
    os_version      = models.CharField("Versão do SO", max_length=100, blank=True)
    tpm = models.JSONField("TpmInfo", null=True, blank=True)

    # RAM slots
    total_memory_slots = models.IntegerField("Slots Totais", null=True, blank=True)
    populated_memory_slots = models.IntegerField("Slots Ocupados", null=True, blank=True)
    memory_modules = models.JSONField("Módulos de Memória", null=True, blank=True)

    manufacturer    = models.CharField("Fabricante", max_length=100, blank=True)
    model           = models.CharField("Modelo", max_length=100, blank=True)
    serial_number   = models.CharField("Serial BIOS", max_length=100, blank=True)
    bios_version    = models.CharField("Versão BIOS", max_length=100, blank=True)
    bios_release    = models.CharField("Data BIOS", max_length=50, blank=True)
    os_caption      = models.CharField("SO Caption", max_length=200, blank=True)
    os_architecture = models.CharField("Arquitetura SO", max_length=50, blank=True)
    os_build        = models.CharField("Build SO", max_length=20, blank=True)
    install_date    = models.CharField("Instalação SO", max_length=30, blank=True)
    last_boot       = models.CharField("Último Boot", max_length=30, blank=True)
    uptime_days     = models.FloatField("Uptime (dias)", null=True, blank=True)

    cpu             = models.CharField("CPU", max_length=200, blank=True)
    ram_gb          = models.FloatField("RAM (GB)", null=True, blank=True)
    disk_space_gb   = models.FloatField("Disco Total (GB)", null=True, blank=True)
    disk_free_gb    = models.FloatField("Disco Livre (GB)", null=True, blank=True)

    network_info    = models.JSONField("Adaptadores Rede", null=True, blank=True)
    gpu_name        = models.CharField("Placa de Vídeo", max_length=200, blank=True)
    gpu_driver      = models.CharField("Driver Vídeo", max_length=100, blank=True)
    antivirus_name  = models.CharField("Antivírus", max_length=200, blank=True)
    av_state        = models.CharField("Estado AV", max_length=50, blank=True)

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