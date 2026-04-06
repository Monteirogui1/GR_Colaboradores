from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
from apps.authentication.models import User
import base64
from cryptography.fernet import Fernet
from django.conf import settings as django_settings

from apps.inventory.models import Machine


def _get_fernet():
    """Deriva chave Fernet de 32 bytes a partir da SECRET_KEY do Django."""
    key_bytes = django_settings.SECRET_KEY.encode()[:32].ljust(32, b'0')
    return Fernet(base64.urlsafe_b64encode(key_bytes))


class StatusBase(models.TextChoices):
    """Status base do sistema - não podem ser alterados após criação"""
    NOVO = 'novo', 'Novo'
    EM_ATENDIMENTO = 'em_atendimento', 'Em Atendimento'
    PARADO = 'parado', 'Parado/Aguardando'
    RESOLVIDO = 'resolvido', 'Resolvido'
    CANCELADO = 'cancelado', 'Cancelado'
    FECHADO = 'fechado', 'Fechado'


class TipoTicket(models.TextChoices):
    """Tipo de ticket"""
    PUBLICO = 'publico', 'Público'
    INTERNO = 'interno', 'Interno'
    AMBOS = 'ambos', 'Ambos'


class TipoHorario(models.TextChoices):
    """Tipo de horário para SLA"""
    HORAS_UTEIS = 'uteis', 'Horas Úteis'
    HORAS_CORRIDAS = 'corridas', 'Horas Corridas'

class DiaSemana(models.IntegerChoices):
    """Dias da semana (0=Segunda ... 6=Domingo)"""
    SEGUNDA  = 0, 'Segunda-feira'
    TERCA    = 1, 'Terça-feira'
    QUARTA   = 2, 'Quarta-feira'
    QUINTA   = 3, 'Quinta-feira'
    SEXTA    = 4, 'Sexta-feira'
    SABADO   = 5, 'Sábado'
    DOMINGO  = 6, 'Domingo'


class TipoNotificacao(models.TextChoices):
    TICKET_CRIADO    = 'ticket_criado',    'Novo ticket'
    NOVA_ACAO        = 'nova_acao',        'Nova ação no ticket'
    STATUS_ALTERADO  = 'status_alterado',  'Status alterado'
    SLA_PROXIMO      = 'sla_proximo',      'SLA próximo do vencimento'
    SLA_VENCIDO      = 'sla_vencido',      'SLA vencido'
    ATRIBUIDO        = 'atribuido',        'Ticket atribuído a você'
    MENCIONADO       = 'mencionado',       'Você foi mencionado'


# ==================== CLASSIFICAÇÕES ====================

class Categoria(models.Model):
    """Categorias de tickets (Dúvida, Problema, Solicitação, etc)"""
    nome = models.CharField("Nome", max_length=100)
    descricao = models.TextField("Descrição", blank=True)
    disponivel_para = models.CharField(
        "Disponível para",
        max_length=20,
        choices=TipoTicket.choices,
        default=TipoTicket.AMBOS
    )
    ativo = models.BooleanField("Ativo", default=True)
    cliente = models.ForeignKey(
        'authentication.User',
        on_delete=models.CASCADE,
        related_name='categorias_tickets',
        limit_choices_to={'is_staff': True}
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Categoria"
        verbose_name_plural = "Categorias"
        ordering = ['nome']
        unique_together = ['nome', 'cliente']

    def __str__(self):
        return self.nome


class Urgencia(models.Model):
    """Urgências do ticket (Urgente, Alta, Média, Baixa)"""
    nome = models.CharField("Nome", max_length=50)
    nivel = models.IntegerField(
        "Nível",
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text="1=Mais urgente, 10=Menos urgente"
    )
    cor = models.CharField("Cor", max_length=7, default="#6c757d", help_text="Código hexadecimal (ex: #ff0000)")
    ativo = models.BooleanField("Ativo", default=True)
    cliente = models.ForeignKey(
        'authentication.User',
        on_delete=models.CASCADE,
        related_name='urgencias_tickets'
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Urgência"
        verbose_name_plural = "Urgências"
        ordering = ['nivel']
        unique_together = ['nome', 'cliente']

    def __str__(self):
        return self.nome


class CategoriaUrgencia(models.Model):
    """Relacionamento entre categorias e urgências permitidas"""
    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE, related_name='urgencias_permitidas')
    urgencia = models.ForeignKey(Urgencia, on_delete=models.CASCADE)

    class Meta:
        verbose_name = "Categoria x Urgência"
        verbose_name_plural = "Categorias x Urgências"
        unique_together = ['categoria', 'urgencia']

    def __str__(self):
        return f"{self.categoria.nome} - {self.urgencia.nome}"


class Status(models.Model):
    """Status personalizados do ticket"""
    nome = models.CharField("Nome", max_length=100)
    status_base = models.CharField(
        "Status Base",
        max_length=20,
        choices=StatusBase.choices,
        help_text="Define o comportamento fundamental - NÃO pode ser alterado após criação"
    )
    requer_justificativa = models.BooleanField("Requer Justificativa", default=False)
    disponivel_para = models.CharField(
        "Disponível para",
        max_length=20,
        choices=TipoTicket.choices,
        default=TipoTicket.AMBOS
    )
    cor = models.CharField("Cor", max_length=7, default="#6c757d")
    ordem = models.IntegerField("Ordem", default=0)
    ativo = models.BooleanField("Ativo", default=True)
    cliente = models.ForeignKey(
        'authentication.User',
        on_delete=models.CASCADE,
        related_name='status_tickets'
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Status"
        verbose_name_plural = "Status"
        ordering = ['ordem', 'nome']
        unique_together = ['nome', 'cliente']

    def __str__(self):
        return f"{self.nome} ({self.get_status_base_display()})"

    def save(self, *args, **kwargs):
        # Impede alteração do status_base após criação
        if self.pk:
            original = Status.objects.get(pk=self.pk)
            if original.status_base != self.status_base:
                raise ValueError("Não é possível alterar o status base após a criação")
        super().save(*args, **kwargs)


class Justificativa(models.Model):
    """Justificativas para status (ex: motivos para status Parado)"""
    nome = models.CharField("Nome", max_length=100)
    descricao = models.TextField("Descrição", blank=True)
    status_vinculados = models.ManyToManyField(
        'Status',
        blank=True,
        related_name='justificativas_vinculadas',
        verbose_name="Status vinculados",
        help_text="Status que podem usar esta justificativa. Deixe vazio para todos."
    )
    ativo = models.BooleanField("Ativo", default=True)
    cliente = models.ForeignKey(
        'authentication.User',
        on_delete=models.CASCADE,
        related_name='justificativas_tickets'
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Justificativa"
        verbose_name_plural = "Justificativas"
        ordering = ['nome']
        unique_together = ['nome', 'cliente']

    def __str__(self):
        return self.nome


class Servico(models.Model):
    """Serviços oferecidos pela empresa"""
    nome = models.CharField("Nome", max_length=100)
    descricao = models.TextField("Descrição", blank=True)
    ativo = models.BooleanField("Ativo", default=True)
    cliente = models.ForeignKey(
        'authentication.User',
        on_delete=models.CASCADE,
        related_name='servicos_tickets'
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Serviço"
        verbose_name_plural = "Serviços"
        ordering = ['nome']
        unique_together = ['nome', 'cliente']

    def __str__(self):
        return self.nome


# ==================== SLA ====================

class ContratoSLA(models.Model):
    """Contrato de SLA - pode conter várias regras"""
    nome = models.CharField("Nome", max_length=100)
    descricao = models.TextField("Descrição", blank=True)
    is_padrao = models.BooleanField(
        "Contrato Padrão",
        default=False,
        help_text="Aplicado a clientes sem contrato específico"
    )
    ativo = models.BooleanField("Ativo", default=True)
    cliente = models.ForeignKey(
        'authentication.User',
        on_delete=models.CASCADE,
        related_name='contratos_sla'
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Contrato SLA"
        verbose_name_plural = "Contratos SLA"
        ordering = ['-is_padrao', 'nome']
        unique_together = ['nome', 'cliente']

    def __str__(self):
        padrao = " (Padrão)" if self.is_padrao else ""
        return f"{self.nome}{padrao}"

    def save(self, *args, **kwargs):
        # Garante apenas um contrato padrão por cliente
        if self.is_padrao:
            ContratoSLA.objects.filter(
                cliente=self.cliente,
                is_padrao=True
            ).exclude(pk=self.pk).update(is_padrao=False)
        super().save(*args, **kwargs)


class RegraSLA(models.Model):
    """Regra dentro de um contrato SLA"""
    contrato = models.ForeignKey(
        ContratoSLA,
        on_delete=models.CASCADE,
        related_name='regras'
    )
    nome = models.CharField("Nome da Regra", max_length=100)
    ordem = models.IntegerField("Ordem", default=0, help_text="Ordem de avaliação das regras")

    # Condições
    categorias = models.ManyToManyField(
        Categoria,
        blank=True,
        verbose_name="Categorias",
        help_text="Deixe vazio para aplicar a todas"
    )
    urgencias = models.ManyToManyField(
        Urgencia,
        blank=True,
        verbose_name="Urgências",
        help_text="Deixe vazio para aplicar a todas"
    )
    servicos = models.ManyToManyField(
        Servico,
        blank=True,
        verbose_name="Serviços",
        help_text="Deixe vazio para aplicar a todos"
    )

    # Pausas
    status_pausam = models.ManyToManyField(
        Status,
        blank=True,
        related_name='regras_sla_pausa',
        verbose_name="Status que pausam o SLA"
    )
    justificativas_pausam = models.ManyToManyField(
        Justificativa,
        blank=True,
        related_name='regras_sla_pausa',
        verbose_name="Justificativas que pausam o SLA"
    )

    # Prazos
    prazo_primeira_resposta = models.IntegerField(
        "Prazo Primeira Resposta (horas)",
        validators=[MinValueValidator(0)],
        null=True,
        blank=True
    )
    prazo_solucao = models.IntegerField(
        "Prazo Solução (horas)",
        validators=[MinValueValidator(1)],
        help_text="Prazo em horas para resolver o ticket"
    )
    limite_acoes_publicas = models.IntegerField(
        "Limite Ações Públicas",
        default=1,
        validators=[MinValueValidator(1)],
        help_text="Limite de ações públicas até encerramento (conceito FCR)"
    )

    # Horário
    tipo_horario = models.CharField(
        "Tipo de Horário",
        max_length=10,
        choices=TipoHorario.choices,
        default=TipoHorario.HORAS_UTEIS
    )

    ativo = models.BooleanField("Ativo", default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Regra SLA"
        verbose_name_plural = "Regras SLA"
        ordering = ['contrato', 'ordem', 'nome']

    def __str__(self):
        return f"{self.contrato.nome} - {self.nome}"

    def aplica_ao_ticket(self, ticket):
        """Verifica se esta regra se aplica ao ticket"""
        # Verifica categoria
        if self.categorias.exists() and ticket.categoria not in self.categorias.all():
            return False

        # Verifica urgência
        if self.urgencias.exists() and ticket.urgencia not in self.urgencias.all():
            return False

        # Verifica serviço
        if self.servicos.exists() and ticket.servico not in self.servicos.all():
            return False

        return True


# ==================== CAMPOS ADICIONAIS ====================

class TipoCampoAdicional(models.TextChoices):
    """Tipos de campos adicionais disponíveis"""
    TEXTO_LINHA = 'texto_linha', 'Texto de uma linha'
    TEXTO_MULTIPLAS = 'texto_multiplas', 'Texto com várias linhas'
    TEXTO_HTML = 'texto_html', 'Texto HTML'
    EXPRESSAO_REGULAR = 'regex', 'Expressão Regular'
    LISTA_VALORES = 'lista', 'Lista de valores'
    LISTA_PESSOAS = 'lista_pessoas', 'Lista de pessoas'
    LISTA_CLIENTES = 'lista_clientes', 'Lista de clientes'
    LISTA_AGENTES = 'lista_agentes', 'Lista de agentes'
    NUMERICO = 'numerico', 'Numérico'
    DATA = 'data', 'Data'
    HORA = 'hora', 'Hora'
    DATA_HORA = 'data_hora', 'Data e Hora'
    TELEFONE = 'telefone', 'Telefone'
    ARQUIVO = 'arquivo', 'Arquivo'


class CampoAdicional(models.Model):
    """Campos adicionais personalizados para tickets"""
    nome = models.CharField("Nome", max_length=100)
    tipo = models.CharField("Tipo", max_length=20, choices=TipoCampoAdicional.choices)
    descricao = models.TextField("Descrição/Ajuda", blank=True)

    # Configurações específicas
    opcoes = models.JSONField(
        "Opções",
        blank=True,
        null=True,
        help_text="Para campos de lista, JSON com as opções disponíveis"
    )
    multipla_selecao = models.BooleanField(
        "Permite Seleção Múltipla",
        default=False,
        help_text="Apenas para campos de lista"
    )
    casas_decimais = models.IntegerField(
        "Casas Decimais",
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(10)],
        help_text="Apenas para campos numéricos"
    )
    expressao_regular = models.CharField(
        "Expressão Regular",
        max_length=500,
        blank=True,
        help_text="Para validação de campos de texto"
    )

    ativo = models.BooleanField("Ativo", default=True)
    cliente = models.ForeignKey(
        'authentication.User',
        on_delete=models.CASCADE,
        related_name='campos_adicionais_tickets'
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Campo Adicional"
        verbose_name_plural = "Campos Adicionais"
        ordering = ['nome']
        unique_together = ['nome', 'cliente']

    def __str__(self):
        return f"{self.nome} ({self.get_tipo_display()})"


class ObrigatoriedadeCampo(models.TextChoices):
    """Obrigatoriedade de campos adicionais"""
    NAO_EXIGIR = 'nao', 'Não exigir'
    SEMPRE = 'sempre', 'Sempre exigir'
    AGENTES = 'agentes', 'Exigir para agentes'
    CLIENTES = 'clientes', 'Exigir para clientes'
    CONDICIONAL = 'condicional', 'Exigir em condições específicas'


class RegraExibicaoCampo(models.Model):
    """Regras para exibição de campos adicionais"""
    nome = models.CharField("Nome da Regra", max_length=100)
    campo = models.ForeignKey(
        CampoAdicional,
        on_delete=models.CASCADE,
        related_name='regras_exibicao'
    )

    # Condições (JSON)
    condicoes = models.JSONField(
        "Condições",
        blank=True,
        null=True,
        help_text="Condições para exibir o campo"
    )

    # Exibição
    colunas = models.IntegerField(
        "Colunas",
        default=12,
        validators=[MinValueValidator(1), MaxValueValidator(12)],
        help_text="Espaço ocupado (1-12, formato Bootstrap)"
    )
    exibir_para = models.CharField(
        "Exibir para",
        max_length=20,
        choices=TipoTicket.choices,
        default=TipoTicket.AMBOS
    )
    obrigatoriedade = models.CharField(
        "Obrigatoriedade",
        max_length=20,
        choices=ObrigatoriedadeCampo.choices,
        default=ObrigatoriedadeCampo.NAO_EXIGIR
    )
    condicoes_obrigatoriedade = models.JSONField(
        "Condições de Obrigatoriedade",
        blank=True,
        null=True,
        help_text="Condições para tornar o campo obrigatório"
    )

    ordem = models.IntegerField("Ordem", default=0)
    ativo = models.BooleanField("Ativo", default=True)
    cliente = models.ForeignKey(
        'authentication.User',
        on_delete=models.CASCADE,
        related_name='regras_exibicao_campos'
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Regra de Exibição de Campo"
        verbose_name_plural = "Regras de Exibição de Campos"
        ordering = ['ordem', 'nome']

    def __str__(self):
        return f"{self.nome} - {self.campo.nome}"


# ==================== TICKET ====================

class CanalAbertura(models.TextChoices):
    """Canais de abertura de tickets"""
    EMAIL = 'email', 'E-mail'
    WEB = 'web', 'Interface Web'
    CHAT = 'chat', 'Chat'
    TELEFONE = 'telefone', 'Telefone'
    WHATSAPP = 'whatsapp', 'WhatsApp'
    API = 'api', 'API'


class Ticket(models.Model):
    """Ticket principal"""
    # Identificação
    numero = models.CharField("Número/Protocolo", max_length=20, unique=True, editable=False)

    # Solicitante (OBRIGATÓRIO)
    solicitante = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='tickets_solicitados',
        verbose_name="Solicitante"
    )

    machine = models.ForeignKey(
        Machine,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tickets',
        verbose_name='Máquina de origem'
    )

    # Classificações
    status = models.ForeignKey(
        Status,
        on_delete=models.PROTECT,
        related_name='tickets',
        verbose_name="Status"
    )
    categoria = models.ForeignKey(
        Categoria,
        on_delete=models.PROTECT,
        related_name='tickets',
        verbose_name="Categoria",
        null=True,
        blank=True
    )
    urgencia = models.ForeignKey(
        Urgencia,
        on_delete=models.PROTECT,
        related_name='tickets',
        verbose_name="Urgência",
        null=True,
        blank=True
    )
    servico = models.ForeignKey(
        Servico,
        on_delete=models.PROTECT,
        related_name='tickets',
        verbose_name="Serviço",
        null=True,
        blank=True
    )
    justificativa = models.ForeignKey(
        Justificativa,
        on_delete=models.SET_NULL,
        related_name='tickets',
        verbose_name="Justificativa",
        null=True,
        blank=True
    )

    # Responsável
    responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='tickets_responsavel',
        verbose_name="Responsável",
        null=True,
        blank=True,
        limit_choices_to={'is_staff': True}
    )

    # Conteúdo
    assunto = models.CharField("Assunto", max_length=255, blank=True)
    descricao = models.TextField("Descrição", blank=True)

    # SLA
    contrato_sla = models.ForeignKey(
        ContratoSLA,
        on_delete=models.SET_NULL,
        related_name='tickets',
        verbose_name="Contrato SLA",
        null=True,
        blank=True
    )
    regra_sla_aplicada = models.ForeignKey(
        RegraSLA,
        on_delete=models.SET_NULL,
        related_name='tickets',
        verbose_name="Regra SLA Aplicada",
        null=True,
        blank=True
    )
    previsao_solucao = models.DateTimeField(
        "Previsão de Solução",
        null=True,
        blank=True
    )
    previsao_manual = models.BooleanField(
        "Previsão Alterada Manualmente",
        default=False
    )
    primeira_resposta_em = models.DateTimeField(
        "Primeira Resposta Em",
        null=True,
        blank=True
    )

    # Metadata
    tipo_ticket = models.CharField(
        "Tipo",
        max_length=20,
        choices=TipoTicket.choices,
        default=TipoTicket.PUBLICO
    )
    canal_abertura = models.CharField(
        "Canal de Abertura",
        max_length=20,
        choices=CanalAbertura.choices,
        default=CanalAbertura.WEB
    )
    tags = models.JSONField("Tags", blank=True, null=True, default=list)
    cc = models.JSONField(
        "CC (E-mails)",
        blank=True,
        null=True,
        default=list,
        help_text="Lista de e-mails para receber cópias"
    )

    # Relacionamentos
    ticket_pai = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        related_name='tickets_filhos',
        verbose_name="Ticket Pai",
        null=True,
        blank=True
    )
    tickets_mesclados = models.ManyToManyField(
        'self',
        symmetrical=False,
        related_name='mesclado_em',
        blank=True,
        verbose_name="Tickets Mesclados"
    )
    tickets_relacionados = models.ManyToManyField(
        'self',
        symmetrical=True,
        blank=True,
        verbose_name="Tickets Relacionados"
    )

    # Tempo
    tempo_pausado = models.DurationField(
        "Tempo Pausado",
        default=timezone.timedelta,
        help_text="Tempo total que o ticket ficou pausado"
    )
    pausado_em = models.DateTimeField(
        "Pausado Em",
        null=True,
        blank=True
    )

    # Timestamps
    criado_em = models.DateTimeField("Criado Em", auto_now_add=True)
    atualizado_em = models.DateTimeField("Atualizado Em", auto_now=True)
    resolvido_em = models.DateTimeField("Resolvido Em", null=True, blank=True)
    fechado_em = models.DateTimeField("Fechado Em", null=True, blank=True)
    cancelado_em = models.DateTimeField("Cancelado Em", null=True, blank=True)

    # Cliente (multi-tenancy)
    cliente = models.ForeignKey(
        'authentication.User',
        on_delete=models.CASCADE,
        related_name='tickets_cliente',
        limit_choices_to={'is_staff': True}
    )

    # Ativos relacionados
    ativos = models.ManyToManyField(
        'ativos.Ativo',
        blank=True,
        related_name='tickets',
        verbose_name='Ativos Relacionados'
    )

    # Campos adicionais (valores)
    campos_adicionais = models.JSONField(
        "Campos Adicionais",
        blank=True,
        null=True,
        default=dict
    )

    # Equipe responsável
    equipe = models.ForeignKey(
        'Equipe',
        on_delete=models.SET_NULL,
        related_name='tickets',
        verbose_name="Equipe",
        null=True,
        blank=True
    )


    class Meta:
        verbose_name = "Ticket"
        verbose_name_plural = "Tickets"
        ordering = ['-criado_em']
        indexes = [
            models.Index(fields=['numero']),
            models.Index(fields=['solicitante', '-criado_em']),
            models.Index(fields=['responsavel', '-criado_em']),
            models.Index(fields=['status', '-criado_em']),
            models.Index(fields=['criado_em']),
        ]

    def __str__(self):
        return f"#{self.numero} - {self.assunto or 'Sem assunto'}"

    def save(self, *args, **kwargs):
        # Gera número do ticket
        if not self.numero:
            ano = timezone.now().year
            ultimo_ticket = Ticket.objects.filter(
                numero__startswith=f"{ano}"
            ).order_by('-numero').first()

            if ultimo_ticket:
                ultimo_num = int(ultimo_ticket.numero.split('-')[1])
                novo_num = ultimo_num + 1
            else:
                novo_num = 1

            self.numero = f"{ano}-{novo_num:06d}"

        # Atualiza timestamps baseado no status
        if self.pk:
            original = Ticket.objects.get(pk=self.pk)

            # Resolvido
            if self.status.status_base == StatusBase.RESOLVIDO and original.status.status_base != StatusBase.RESOLVIDO:
                self.resolvido_em = timezone.now()

            # Fechado
            if self.status.status_base == StatusBase.FECHADO and original.status.status_base != StatusBase.FECHADO:
                self.fechado_em = timezone.now()

            # Cancelado
            if self.status.status_base == StatusBase.CANCELADO and original.status.status_base != StatusBase.CANCELADO:
                self.cancelado_em = timezone.now()

            # Gerenciar pausa
            if self.status.status_base == StatusBase.PARADO and original.status.status_base != StatusBase.PARADO:
                self.pausado_em = timezone.now()
            elif self.status.status_base != StatusBase.PARADO and original.status.status_base == StatusBase.PARADO:
                if self.pausado_em:
                    tempo_pausa = timezone.now() - self.pausado_em
                    self.tempo_pausado += tempo_pausa
                    self.pausado_em = None

        super().save(*args, **kwargs)

        # Calcula SLA após salvar
        if not self.previsao_manual:
            self.calcular_prazo_uteis()

    def calcular_prazo_uteis(dt_inicio, horas_prazo, horarios, feriados_qs):
        """
        Calcula dt_inicio + horas_prazo em horas úteis reais.

        Args:
            dt_inicio    : datetime — início do prazo
            horas_prazo  : int     — horas de SLA
            horarios     : QuerySet[HorarioAtendimento]
            feriados_qs  : QuerySet[Feriado]

        Returns:
            datetime — previsão de solução em horas úteis
        """
        from datetime import timedelta, datetime, time as dtime
        from django.utils import timezone

        if not horarios.exists():
            # Sem horário configurado: usa horas corridas
            return dt_inicio + timedelta(hours=horas_prazo)

        # Mapa dia_semana → lista de janelas (hora_inicio, hora_fim)
        janelas_por_dia = {}
        for h in horarios.filter(ativo=True):
            janelas_por_dia.setdefault(h.dia_semana, []).append(
                (h.hora_inicio, h.hora_fim)
            )

        # Cache de feriados (data → True)
        feriados_set = set()
        for f in feriados_qs:
            if f.recorrente:
                # Adiciona para vários anos ao redor do período
                for ano in range(dt_inicio.year, dt_inicio.year + 5):
                    try:
                        feriados_set.add(f.data.replace(year=ano))
                    except ValueError:
                        pass  # 29/fev em ano não bissexto
            else:
                feriados_set.add(f.data)

        def is_uteis(dt):
            """Verifica se dt está dentro de um horário útil."""
            if dt.date() in feriados_set:
                return False
            dia = dt.weekday()  # 0=segunda … 6=domingo
            janelas = janelas_por_dia.get(dia, [])
            hora_atual = dt.time()
            return any(inicio <= hora_atual < fim for inicio, fim in janelas)

        def proxima_janela_inicio(dt):
            """Retorna o próximo início de janela útil a partir de dt."""
            # Tenta o mesmo dia
            dia = dt.weekday()
            janelas_hoje = sorted(janelas_por_dia.get(dia, []))
            hora_atual = dt.time()

            for inicio, _ in janelas_hoje:
                if inicio > hora_atual and dt.date() not in feriados_set:
                    return dt.replace(hour=inicio.hour, minute=inicio.minute,
                                      second=0, microsecond=0)

            # Próximos dias
            for dias_a_frente in range(1, 8):
                prox_dt = dt + timedelta(days=dias_a_frente)
                if prox_dt.date() in feriados_set:
                    continue
                dia_prox = prox_dt.weekday()
                janelas_prox = sorted(janelas_por_dia.get(dia_prox, []))
                if janelas_prox:
                    inicio = janelas_prox[0][0]
                    return prox_dt.replace(hour=inicio.hour, minute=inicio.minute,
                                           second=0, microsecond=0)

            return dt + timedelta(days=1)  # Fallback

        # Se não está em horário útil, avança para o próximo início
        atual = dt_inicio
        if not is_uteis(atual):
            atual = proxima_janela_inicio(atual)

        horas_restantes = horas_prazo

        MAX_ITER = horas_prazo * 10 + 1000  # Proteção contra loop infinito
        iteracoes = 0

        while horas_restantes > 0 and iteracoes < MAX_ITER:
            iteracoes += 1
            dia = atual.weekday()

            if atual.date() in feriados_set:
                atual = proxima_janela_inicio(atual)
                continue

            janelas_hoje = sorted(janelas_por_dia.get(dia, []))
            if not janelas_hoje:
                atual = proxima_janela_inicio(atual)
                continue

            # Encontrar janela atual
            hora_atual = atual.time()
            janela_corrente = None
            for inicio, fim in janelas_hoje:
                if inicio <= hora_atual < fim:
                    janela_corrente = (inicio, fim)
                    break

            if janela_corrente is None:
                # Fora de janela — avança para próxima
                atual = proxima_janela_inicio(atual)
                continue

            # Horas disponíveis até o fim desta janela
            fim_janela = atual.replace(
                hour=janela_corrente[1].hour,
                minute=janela_corrente[1].minute,
                second=0, microsecond=0
            )
            horas_na_janela = (fim_janela - atual).total_seconds() / 3600

            if horas_restantes <= horas_na_janela:
                # Prazo termina nesta janela
                atual = atual + timedelta(hours=horas_restantes)
                horas_restantes = 0
            else:
                # Consome toda a janela e vai para a próxima
                horas_restantes -= horas_na_janela
                atual = proxima_janela_inicio(fim_janela)

        return atual

    @property
    def esta_vencido(self):
        """Verifica se o ticket está vencido"""
        if not self.previsao_solucao:
            return False
        return timezone.now() > self.previsao_solucao

    @property
    def percentual_sla_usado(self):
        """Calcula percentual do SLA já utilizado"""
        if not self.previsao_solucao:
            return None

        total = (self.previsao_solucao - self.criado_em).total_seconds()
        usado = (timezone.now() - self.criado_em - self.tempo_pausado).total_seconds()

        return (usado / total) * 100 if total > 0 else 0


class TipoAcao(models.TextChoices):
    """Tipos de ação no ticket"""
    PUBLICA = 'publica', 'Ação Pública'
    INTERNA = 'interna', 'Ação Interna'
    MENSAGEM = 'mensagem', 'Mensagem Interna'


class AcaoTicket(models.Model):
    """Ações e respostas em um ticket"""
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name='acoes'
    )
    tipo = models.CharField(
        "Tipo",
        max_length=20,
        choices=TipoAcao.choices,
        default=TipoAcao.PUBLICA
    )
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='acoes_tickets',
        verbose_name="Autor"
    )
    conteudo = models.TextField("Conteúdo")
    conteudo_html = models.TextField("Conteúdo HTML", blank=True)

    # Metadata
    tempo_trabalhado = models.DurationField(
        "Tempo Trabalhado",
        null=True,
        blank=True,
        help_text="Tempo de trabalho apontado nesta ação"
    )

    criado_em = models.DateTimeField("Criado Em", auto_now_add=True)
    editado_em = models.DateTimeField("Editado Em", null=True, blank=True)

    class Meta:
        verbose_name = "Ação do Ticket"
        verbose_name_plural = "Ações do Ticket"
        ordering = ['criado_em']

    def __str__(self):
        return f"{self.ticket.numero} - {self.get_tipo_display()} por {self.autor.username}"

    def save(self, *args, **kwargs):
        is_new = not self.pk
        super().save(*args, **kwargs)

        # Marca primeira resposta
        if is_new and self.tipo == TipoAcao.PUBLICA:
            if not self.ticket.primeira_resposta_em and self.autor.is_staff:
                Ticket.objects.filter(pk=self.ticket.pk).update(
                    primeira_resposta_em=self.criado_em
                )


class AnexoTicket(models.Model):
    """Anexos do ticket"""
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name='anexos'
    )
    acao = models.ForeignKey(
        AcaoTicket,
        on_delete=models.CASCADE,
        related_name='anexos',
        null=True,
        blank=True
    )
    arquivo = models.FileField(
        "Arquivo",
        upload_to='tickets/anexos/%Y/%m/',
        max_length=255
    )
    nome_original = models.CharField("Nome Original", max_length=255)
    tamanho = models.BigIntegerField("Tamanho (bytes)")
    tipo_mime = models.CharField("Tipo MIME", max_length=100)

    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='anexos_tickets'
    )
    criado_em = models.DateTimeField("Criado Em", auto_now_add=True)

    class Meta:
        verbose_name = "Anexo"
        verbose_name_plural = "Anexos"
        ordering = ['criado_em']

    def __str__(self):
        return f"{self.ticket.numero} - {self.nome_original}"


class HistoricoTicket(models.Model):
    """Histórico de alterações do ticket"""
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name='historico'
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='historico_tickets'
    )
    campo = models.CharField("Campo", max_length=100)
    valor_anterior = models.TextField("Valor Anterior", blank=True)
    valor_novo = models.TextField("Valor Novo", blank=True)
    criado_em = models.DateTimeField("Criado Em", auto_now_add=True)

    class Meta:
        verbose_name = "Histórico"
        verbose_name_plural = "Histórico"
        ordering = ['-criado_em']

    def __str__(self):
        return f"{self.ticket.numero} - {self.campo} alterado por {self.usuario.username}"


# ==================== AUTOMAÇÕES ====================

class Gatilho(models.Model):
    """Gatilhos para automação"""
    nome = models.CharField("Nome", max_length=100)
    descricao = models.TextField("Descrição", blank=True)

    # Condições (JSON)
    condicoes = models.JSONField(
        "Condições",
        help_text="Quando o gatilho deve disparar"
    )

    # Ações (JSON)
    acoes = models.JSONField(
        "Ações",
        help_text="O que o gatilho deve fazer"
    )

    ativo = models.BooleanField("Ativo", default=True)
    ordem = models.IntegerField("Ordem", default=0)
    cliente = models.ForeignKey(
        'authentication.User',
        on_delete=models.CASCADE,
        related_name='gatilhos_tickets'
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Gatilho"
        verbose_name_plural = "Gatilhos"
        ordering = ['ordem', 'nome']

    def __str__(self):
        return self.nome


class Macro(models.Model):
    """Macros para aplicação rápida de ações"""
    nome = models.CharField("Nome", max_length=100)
    descricao = models.TextField("Descrição", blank=True)

    # Ações (JSON)
    acoes = models.JSONField(
        "Ações",
        help_text="Alterações a serem aplicadas"
    )

    ativo = models.BooleanField("Ativo", default=True)
    cliente = models.ForeignKey(
        'authentication.User',
        on_delete=models.CASCADE,
        related_name='macros_tickets'
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Macro"
        verbose_name_plural = "Macros"
        ordering = ['nome']

    def __str__(self):
        return self.nome


# ==================== PESQUISA DE SATISFAÇÃO ====================

class PesquisaSatisfacao(models.Model):
    """Pesquisa de satisfação enviada ao cliente"""
    ticket = models.OneToOneField(
        Ticket,
        on_delete=models.CASCADE,
        related_name='pesquisa_satisfacao'
    )
    nota = models.IntegerField(
        "Nota",
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        null=True,
        blank=True
    )
    comentario = models.TextField("Comentário", blank=True)

    enviada_em = models.DateTimeField("Enviada Em", auto_now_add=True)
    respondida_em = models.DateTimeField("Respondida Em", null=True, blank=True)

    class Meta:
        verbose_name = "Pesquisa de Satisfação"
        verbose_name_plural = "Pesquisas de Satisfação"

    def __str__(self):
        status = f"Nota: {self.nota}" if self.nota else "Não respondida"
        return f"{self.ticket.numero} - {status}"


class ConfiguracaoEmail(models.Model):
    """
    Configuração de e-mail IMAP/SMTP por cliente, cadastrável via interface.

    Armazena credenciais criptografadas com Fernet (AES-128-CBC),
    derivado da SECRET_KEY do Django. Nunca ficam em texto puro no banco.
    """

    class ProvedorEmail(models.TextChoices):
        GMAIL = 'gmail', 'Gmail'
        OUTLOOK = 'outlook', 'Outlook / Microsoft 365'
        YAHOO = 'yahoo', 'Yahoo'
        CUSTOM = 'custom', 'Servidor personalizado'

    # Multi-tenancy: um registro por cliente (User is_staff)
    cliente = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='configuracao_email',
        limit_choices_to={'is_staff': True},
        verbose_name='Cliente (administrador)',
    )

    provedor = models.CharField(
        'Provedor',
        max_length=20,
        choices=ProvedorEmail.choices,
        default=ProvedorEmail.GMAIL,
    )

    # ── SMTP (envio) ──────────────────────────────────────────────────────────
    smtp_host = models.CharField('Servidor SMTP', max_length=255, default='smtp.gmail.com')
    smtp_port = models.PositiveIntegerField('Porta SMTP', default=587)
    smtp_use_tls = models.BooleanField('Usar TLS', default=True)

    # ── IMAP (recebimento) ────────────────────────────────────────────────────
    imap_server = models.CharField('Servidor IMAP', max_length=255, default='imap.gmail.com')
    imap_port = models.PositiveIntegerField('Porta IMAP', default=993)

    # ── Credenciais (armazenadas criptografadas) ──────────────────────────────
    email_usuario = models.EmailField('E-mail', max_length=255)

    # Campos _enc guardam o valor Fernet-criptografado em base64
    _senha_enc = models.TextField('Senha (criptografada)', db_column='senha_enc', blank=True)

    # ── Configurações de comportamento ────────────────────────────────────────
    auto_criar_usuarios = models.BooleanField('Criar usuários automaticamente', default=True)
    processar_anexos = models.BooleanField('Processar anexos', default=True)
    enviar_confirmacao = models.BooleanField('Enviar confirmação ao solicitante', default=True)
    notificar_agente_resposta = models.BooleanField('Notificar técnico quando cliente responde', default=True)
    notificar_cliente_resposta = models.BooleanField('Notificar cliente quando técnico responde', default=True)

    site_url = models.URLField(
        'URL do sistema',
        max_length=255,
        default='https://suporte.suaempresa.com',
        help_text='URL base usada nos links dos e-mails enviados',
    )

    ativo = models.BooleanField('Ativo', default=True)

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configuração de E-mail'
        verbose_name_plural = 'Configurações de E-mail'

    def __str__(self):
        return f'Config e-mail — {self.email_usuario}'

    # ── API de senha criptografada ────────────────────────────────────────────

    def set_senha(self, senha_plain: str):
        """Criptografa e armazena a senha."""
        if not senha_plain:
            return
        f = _get_fernet()
        self._senha_enc = f.encrypt(senha_plain.encode()).decode()

    def get_senha(self) -> str:
        """Descriptografa e retorna a senha em texto puro."""
        if not self._senha_enc:
            return ''
        try:
            f = _get_fernet()
            return f.decrypt(self._senha_enc.encode()).decode()
        except Exception:
            return ''

    # ── Método utilitário para o command ─────────────────────────────────────

    def to_email_config_dict(self) -> dict:
        """
        Retorna dicionário no mesmo formato de settings.TICKET_EMAIL_CONFIG,
        compatível com process_ticket_emails sem alterações na estrutura.
        """
        return {
            'IMAP_SERVER': self.imap_server,
            'IMAP_PORT': self.imap_port,
            'EMAIL_USER': self.email_usuario,
            'EMAIL_PASSWORD': self.get_senha(),
            'AUTO_CREATE_USERS': self.auto_criar_usuarios,
            'PROCESS_ATTACHMENTS': self.processar_anexos,
            'SEND_CONFIRMATION': self.enviar_confirmacao,
            'NOTIFY_AGENT_ON_REPLY': self.notificar_agente_resposta,
            'NOTIFY_CLIENT_ON_REPLY': self.notificar_cliente_resposta,
            'SITE_URL': self.site_url,
        }

    # ── Presets por provedor ──────────────────────────────────────────────────

    PRESETS = {
        'gmail': {
            'smtp_host': 'smtp.gmail.com', 'smtp_port': 587,
            'imap_server': 'imap.gmail.com', 'imap_port': 993,
        },
        'outlook': {
            'smtp_host': 'smtp.office365.com', 'smtp_port': 587,
            'imap_server': 'outlook.office365.com', 'imap_port': 993,
        },
        'yahoo': {
            'smtp_host': 'smtp.mail.yahoo.com', 'smtp_port': 587,
            'imap_server': 'imap.mail.yahoo.com', 'imap_port': 993,
        },
    }


class HorarioAtendimento(models.Model):
    """
    Janela de horário de atendimento por dia da semana.
    Usada para calcular SLA em horas úteis.
    Um cliente pode ter múltiplas janelas (uma por dia ativo).
    """
    nome = models.CharField("Nome", max_length=100,
                            help_text="Ex: Horário Padrão, Horário Estendido")
    cliente = models.ForeignKey(
        'authentication.User',
        on_delete=models.CASCADE,
        related_name='horarios_atendimento'
    )
    dia_semana = models.IntegerField(
        "Dia da Semana",
        choices=DiaSemana.choices
    )
    hora_inicio = models.TimeField("Hora de Início")
    hora_fim = models.TimeField("Hora de Fim")
    ativo = models.BooleanField("Ativo", default=True)

    class Meta:
        verbose_name = "Horário de Atendimento"
        verbose_name_plural = "Horários de Atendimento"
        ordering = ['dia_semana', 'hora_inicio']
        unique_together = ['cliente', 'nome', 'dia_semana']

    def __str__(self):
        return (
            f"{self.nome} — {self.get_dia_semana_display()} "
            f"{self.hora_inicio:%H:%M}–{self.hora_fim:%H:%M}"
        )


class Feriado(models.Model):
    """Feriados que suspendem o atendimento (para cálculo SLA em horas úteis)."""
    nome = models.CharField("Nome", max_length=100)
    data = models.DateField("Data")
    recorrente = models.BooleanField(
        "Recorrente anualmente",
        default=False,
        help_text="Se marcado, repete todo ano na mesma data"
    )
    cliente = models.ForeignKey(
        'authentication.User',
        on_delete=models.CASCADE,
        related_name='feriados'
    )

    class Meta:
        verbose_name = "Feriado"
        verbose_name_plural = "Feriados"
        ordering = ['data']
        unique_together = ['cliente', 'data', 'nome']

    def __str__(self):
        return f"{self.nome} ({self.data:%d/%m/%Y})"

    def eh_feriado_hoje(self, data_verificar):
        """Verifica se esta data é feriado (considerando recorrência)."""
        if self.recorrente:
            return (self.data.month == data_verificar.month and
                    self.data.day == data_verificar.day)
        return self.data == data_verificar


class TemplateResposta(models.Model):
    """
    Templates de resposta rápida para agentes.
    Suporta variáveis como {ticket.numero}, {ticket.solicitante}, etc.
    """
    nome = models.CharField("Nome", max_length=100)
    descricao = models.TextField("Descrição", blank=True)

    # Conteúdo HTML (gerado pelo editor Quill)
    conteudo = models.TextField(
        "Conteúdo",
        help_text="HTML da resposta. Suporta variáveis: {ticket.numero}, "
                  "{ticket.assunto}, {ticket.solicitante}, {ticket.responsavel}"
    )

    ativo = models.BooleanField("Ativo", default=True)
    ordem = models.IntegerField("Ordem", default=0)
    cliente = models.ForeignKey(
        'authentication.User',
        on_delete=models.CASCADE,
        related_name='templates_resposta'
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Template de Resposta"
        verbose_name_plural = "Templates de Resposta"
        ordering = ['ordem', 'nome']
        unique_together = ['nome', 'cliente']

    def __str__(self):
        return self.nome

    @property
    def conteudo_json(self):
        """Retorna JSON seguro para uso inline no template HTML."""
        import json
        return json.dumps({'conteudo': self.conteudo, 'nome': self.nome})

    def substituir_variaveis(self, ticket):
        """Substitui variáveis no conteúdo pelo contexto do ticket."""
        conteudo = self.conteudo
        variaveis = {
            '{ticket.numero}': ticket.numero,
            '{ticket.assunto}': ticket.assunto or '',
            '{ticket.solicitante}': ticket.solicitante.get_full_name() or ticket.solicitante.username if ticket.solicitante else '',
            '{ticket.responsavel}': ticket.responsavel.get_full_name() or ticket.responsavel.username if ticket.responsavel else '',
            '{ticket.status}': ticket.status.nome if ticket.status else '',
            '{ticket.categoria}': ticket.categoria.nome if ticket.categoria else '',
            '{ticket.urgencia}': ticket.urgencia.nome if ticket.urgencia else '',
        }
        for var, val in variaveis.items():
            conteudo = conteudo.replace(var, str(val))
        return conteudo


class Equipe(models.Model):
    """Equipe de agentes — agrupa agentes para roteamento de tickets."""
    nome = models.CharField("Nome", max_length=100)
    descricao = models.TextField("Descrição", blank=True)
    email = models.EmailField("E-mail da equipe", blank=True,
                              help_text="E-mail de contato/notificação da equipe")
    ativo = models.BooleanField("Ativo", default=True)
    ordem = models.IntegerField("Ordem", default=0)

    cliente = models.ForeignKey(
        'authentication.User',
        on_delete=models.CASCADE,
        related_name='equipes'
    )
    agentes = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='equipes_membro',
        limit_choices_to={'is_staff': True},
        verbose_name="Agentes"
    )

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Equipe"
        verbose_name_plural = "Equipes"
        ordering = ['ordem', 'nome']
        unique_together = ['nome', 'cliente']

    def __str__(self):
        return self.nome

    def agente_com_menor_carga(self):
        """
        Retorna o agente da equipe com menos tickets abertos.
        Usado para distribuição automática de tickets.
        """
        from django.db.models import Count, Q
        return (
            self.agentes
            .filter(is_active=True)
            .annotate(
                tickets_abertos=Count(
                    'tickets_responsavel',
                    filter=Q(
                        tickets_responsavel__status__status_base__in=[
                            'novo', 'em_atendimento', 'parado'
                        ]
                    )
                )
            )
            .order_by('tickets_abertos')
            .first()
        )


class NotificacaoTicket(models.Model):
    """
    Notificação in-app para agentes e solicitantes.
    Exibida como badge no header e lista de notificações.
    """
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notificacoes_tickets'
    )
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name='notificacoes',
        null=True, blank=True
    )
    tipo = models.CharField(
        "Tipo",
        max_length=30,
        choices=TipoNotificacao.choices
    )
    titulo = models.CharField("Título", max_length=200)
    mensagem = models.TextField("Mensagem", blank=True)
    lida = models.BooleanField("Lida", default=False)
    lida_em = models.DateTimeField("Lida em", null=True, blank=True)
    criado_em = models.DateTimeField("Criado em", auto_now_add=True)

    class Meta:
        verbose_name = "Notificação"
        verbose_name_plural = "Notificações"
        ordering = ['-criado_em']
        indexes = [
            models.Index(fields=['usuario', 'lida', '-criado_em']),
        ]

    def __str__(self):
        return f"{self.usuario.username} — {self.titulo}"

    def marcar_lida(self):
        if not self.lida:
            self.lida = True
            self.lida_em = timezone.now()
            self.save(update_fields=['lida', 'lida_em'])

    @property
    def icone(self):
        icones = {
            'ticket_criado': 'bi-ticket-detailed',
            'nova_acao': 'bi-chat-left-text',
            'status_alterado': 'bi-arrow-repeat',
            'sla_proximo': 'bi-exclamation-triangle',
            'sla_vencido': 'bi-x-octagon',
            'atribuido': 'bi-person-check',
            'mencionado': 'bi-at',
        }
        return icones.get(self.tipo, 'bi-bell')

    @property
    def cor(self):
        cores = {
            'ticket_criado': '#1a73e8',
            'nova_acao': '#7c3aed',
            'status_alterado': '#0891b2',
            'sla_proximo': '#d97706',
            'sla_vencido': '#ef4444',
            'atribuido': '#16a34a',
            'mencionado': '#db2777',
        }
        return cores.get(self.tipo, '#6b7280')