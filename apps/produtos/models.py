from django.db import models
from apps.categorias.models import Categoria
from apps.fornecedor.models import Fornecedor
from apps.marcas.models import Marca
from apps.shared.models import Cliente, ClienteBaseModel


# Unidade de Medida como model (remova o TextChoices, pois o model resolve tudo)
class UnidadeMedida(ClienteBaseModel, models.Model):
    nome = models.CharField(max_length=30)
    sigla = models.CharField(max_length=10)

    def __str__(self):
        return f"{self.sigla} ({self.nome})"

class Produto(ClienteBaseModel, models.Model):
    nome = models.CharField(max_length=500)
    categoria = models.ForeignKey(Categoria, on_delete=models.PROTECT, related_name='produtos', limit_choices_to={'status': True})
    marca = models.ForeignKey(Marca, on_delete=models.PROTECT, related_name='produtos', limit_choices_to={'status': True})
    fornecedor = models.ForeignKey(Fornecedor, on_delete=models.PROTECT, related_name='produtos', limit_choices_to={'status': True})
    descricao = models.TextField(null=True, blank=True)
    num_serie = models.CharField(max_length=200, null=True, blank=True)
    preco_custo = models.DecimalField(max_digits=20, decimal_places=2)
    preco_venda = models.DecimalField(max_digits=20, decimal_places=2)
    imagem = models.ImageField(null=True, blank=True, upload_to='produtos/')
    status = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nome']

    def __str__(self):
        return self.nome

# Produto pode ter N variações (roupa, combustível por bomba, sabores, etc)
class VariacaoProduto(ClienteBaseModel, models.Model):
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE, related_name='variacoes')
    tamanho = models.CharField(max_length=10, blank=True, null=True)  # Opcional, pode ser cor, volume, etc.
    quantidade = models.DecimalField(max_digits=20, decimal_places=4, default=0)  # Use DecimalField para universalidade!
    unidade = models.ForeignKey(UnidadeMedida, on_delete=models.PROTECT)
    estoque_minimo = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    codigo_barras = models.CharField(max_length=128, null=True, blank=True, unique=True)
    barcode_image = models.ImageField(upload_to='barcodes/', blank=True, null=True)
    qr_code = models.ImageField(upload_to='qrcodes/', blank=True, null=True)

    class Meta:
        ordering = ['tamanho']

    def __str__(self):
        return f"{self.produto.nome} - {self.tamanho or self.unidade}"

# Campos Dinâmicos (produto universal para qualquer segmento)
class CampoDinamico(ClienteBaseModel, models.Model):
    nome = models.CharField(max_length=100)
    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE, related_name='campos_dinamicos')
    tipo = models.CharField(max_length=20, choices=[
        ('texto', 'Texto'), ('numero', 'Número'), ('data', 'Data'), ('bool', 'Booleano')
    ])
    obrigatorio = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.nome} ({self.categoria})"

class ValorCampoDinamico(ClienteBaseModel, models.Model):
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE, related_name='valores_campos')
    campo = models.ForeignKey(CampoDinamico, on_delete=models.CASCADE)
    valor = models.CharField(max_length=500)

class ProdutoUnidade(ClienteBaseModel, models.Model):
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE, related_name='unidades')
    unidade = models.ForeignKey(UnidadeMedida, on_delete=models.PROTECT)
    fator_conversao = models.DecimalField(max_digits=15, decimal_places=6, default=1)  # Ex: 1 caixa = 12 unidades

    def __str__(self):
        return f"{self.produto} - {self.unidade} (1un = {self.fator_conversao}{self.unidade})"


class ProdutoComposicao(ClienteBaseModel, models.Model):
    produto_pai = models.ForeignKey(Produto, related_name='kits', on_delete=models.CASCADE)
    produto_componente = models.ForeignKey(Produto, related_name='componentes', on_delete=models.CASCADE)
    quantidade = models.DecimalField(max_digits=10, decimal_places=3)

    def __str__(self):
        return f"{self.produto_pai} contém {self.quantidade} x {self.produto_componente}"

class ParametroEstoque(ClienteBaseModel, models.Model):
    produto = models.OneToOneField(Produto, on_delete=models.CASCADE, related_name='parametro_estoque')
    estoque_minimo = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    estoque_maximo = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    alerta_reposicao = models.BooleanField(default=True)

    def __str__(self):
        return f"Parâmetros de Estoque: {self.produto.nome}"