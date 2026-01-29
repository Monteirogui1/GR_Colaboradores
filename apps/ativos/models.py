from django.db import models
from apps.shared.models import ClienteBaseModel
from apps.categorias.models import Categoria
from apps.fornecedor.models import Fornecedor
from apps.marcas.models import Marca
from apps.inventory.models import Machine
from apps.authentication.models import User


class Localizacao(ClienteBaseModel, models.Model):
    nome = models.CharField("Nome da Filial", max_length=200)
    endereco = models.TextField("Endereço", blank=True, null=True)
    status = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nome']
        verbose_name = "Localização"
        verbose_name_plural = "Localizações"

    def __str__(self):
        return self.nome


class StatusAtivo(ClienteBaseModel, models.Model):
    nome = models.CharField("Nome do Status", max_length=100)
    cor = models.CharField("Cor (hex)", max_length=7, default="#6c757d", help_text="Ex: #28a745")
    descricao = models.TextField("Descrição", blank=True, null=True)
    is_active = models.BooleanField("Ativo", default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nome']
        verbose_name = "Status de Ativo"
        verbose_name_plural = "Status de Ativos"

    def __str__(self):
        return self.nome


class Ativo(ClienteBaseModel, models.Model):
    # Informações Básicas
    nome = models.CharField("Nome", max_length=500)
    etiqueta = models.CharField("Etiqueta", max_length=100, unique=True)
    numero_serie = models.CharField("Número de Série", max_length=200, blank=True, null=True)
    codigo_referencia = models.CharField("Código Referência", max_length=100, blank=True, null=True)

    # Relacionamentos
    categoria = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Categoria")
    fornecedor = models.ForeignKey(Fornecedor, on_delete=models.SET_NULL, null=True, blank=True,
                                   verbose_name="Fornecedor")
    localizacao = models.ForeignKey(Localizacao, on_delete=models.SET_NULL, null=True, blank=True,
                                    verbose_name="Localização")
    marca = models.ForeignKey(Marca, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Marca")
    computador = models.ForeignKey(Machine, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Computador")
    status = models.ForeignKey(StatusAtivo, on_delete=models.PROTECT, verbose_name="Status")

    # Detalhes
    fabricante = models.CharField("Fabricante", max_length=200, blank=True, null=True)
    modelo = models.CharField("Modelo", max_length=200, blank=True, null=True)

    # Datas e Valores
    data_compra = models.DateField("Data de Compra", blank=True, null=True)
    garantia_ate = models.DateField("Garantia Até", blank=True, null=True)
    custo = models.DecimalField("Custo", max_digits=10, decimal_places=2, blank=True, null=True)

    # Outros
    descricao = models.TextField("Descrição", blank=True, null=True)
    auditoria = models.TextField("Auditoria", blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Ativo"
        verbose_name_plural = "Ativos"

    def __str__(self):
        return f"{self.etiqueta} - {self.nome}"


class AtivoUtilizador(models.Model):
    ativo = models.ForeignKey(Ativo, on_delete=models.CASCADE, related_name='utilizadores')
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Usuário")
    data_inicio = models.DateField("Data Início")
    data_fim = models.DateField("Data Fim", blank=True, null=True)
    observacoes = models.TextField("Observações", blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-data_inicio']
        verbose_name = "Utilizador do Ativo"
        verbose_name_plural = "Utilizadores dos Ativos"

    def __str__(self):
        return f"{self.ativo.etiqueta} - {self.usuario.username}"


class AtivoAnexo(models.Model):
    ativo = models.ForeignKey(Ativo, on_delete=models.CASCADE, related_name='anexos')
    titulo = models.CharField("Título", max_length=200)
    arquivo = models.FileField("Arquivo", upload_to='ativos/anexos/')
    descricao = models.TextField("Descrição", blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Anexo do Ativo"
        verbose_name_plural = "Anexos dos Ativos"

    def __str__(self):
        return f"{self.ativo.etiqueta} - {self.titulo}"


class AtivoHistorico(models.Model):
    ativo = models.ForeignKey(Ativo, on_delete=models.CASCADE, related_name='historico')
    campo_alterado = models.CharField("Campo Alterado", max_length=100, blank=True, null=True)
    valor_anterior = models.TextField("Valor Anterior", blank=True, null=True)
    valor_novo = models.TextField("Valor Novo", blank=True, null=True)
    descricao = models.TextField("Descrição")
    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="Usuário")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Histórico do Ativo"
        verbose_name_plural = "Históricos dos Ativos"

    def __str__(self):
        return f"{self.ativo.etiqueta} - {self.created_at.strftime('%d/%m/%Y %H:%M')}"


