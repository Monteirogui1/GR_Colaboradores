from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
from apps.authentication.models import User


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

    # Campos adicionais (valores)
    campos_adicionais = models.JSONField(
        "Campos Adicionais",
        blank=True,
        null=True,
        default=dict
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
            from datetime import datetime
            ano = datetime.now().year
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
            self.calcular_sla()

    def calcular_sla(self):
        """Calcula a previsão de solução baseada no SLA"""
        if self.previsao_manual:
            return

        # Busca contrato SLA
        contrato = self.contrato_sla or ContratoSLA.objects.filter(
            cliente=self.cliente,
            is_padrao=True,
            ativo=True
        ).first()

        if not contrato:
            return

        # Busca regra aplicável
        for regra in contrato.regras.filter(ativo=True).order_by('ordem'):
            if regra.aplica_ao_ticket(self):
                self.regra_sla_aplicada = regra
                self.contrato_sla = contrato

                # Calcula previsão
                from datetime import timedelta
                prazo = timedelta(hours=regra.prazo_solucao)

                # TODO: Considerar horas úteis vs corridas
                # TODO: Subtrair tempo pausado
                self.previsao_solucao = self.criado_em + prazo

                Ticket.objects.filter(pk=self.pk).update(
                    regra_sla_aplicada=self.regra_sla_aplicada,
                    contrato_sla=self.contrato_sla,
                    previsao_solucao=self.previsao_solucao
                )
                break

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