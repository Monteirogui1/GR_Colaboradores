from django.db import models
from django.contrib.auth.models import User
from apps.produtos.models import Produto, VariacaoProduto
from apps.fornecedor.models import Fornecedor
from apps.shared.models import Cliente, ClienteBaseModel
from django.conf import settings


class Lote(ClienteBaseModel, models.Model):
    
    variacao = models.ForeignKey(VariacaoProduto, on_delete=models.PROTECT, related_name='lotes')
    fornecedor = models.ForeignKey(Fornecedor, on_delete=models.PROTECT, null=True, blank=True)
    numero_lote = models.CharField(max_length=100)
    quantidade = models.DecimalField(max_digits=15, decimal_places=4)
    preco_unitario = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    documento_nfe = models.FileField(upload_to='notas_fiscais/', null=True, blank=True)
    data_entrada = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"Lote {self.numero_lote} - {self.variacao.produto.nome} ({self.quantidade} {self.variacao.unidade})"



class TipoMovimentacao(ClienteBaseModel, models.Model):
    
    nome = models.CharField(max_length=100)
    entrada_saida = models.CharField(max_length=10, choices=(('Entrada', 'Entrada'), ('Saída', 'Saída')))
    descricao = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.nome

class Movimentacao(ClienteBaseModel, models.Model):
    
    tipo = models.ForeignKey(TipoMovimentacao, on_delete=models.PROTECT)
    variacao = models.ForeignKey(VariacaoProduto, on_delete=models.PROTECT, related_name='movimentacoes')
    quantidade = models.DecimalField(max_digits=15, decimal_places=4)
    data = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    lote = models.ForeignKey('Lote', on_delete=models.PROTECT, null=True, blank=True)
    observacao = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.tipo} - {self.variacao} ({self.quantidade}) em {self.data:%d/%m/%Y}"

class HistoricoEstoque(ClienteBaseModel, models.Model):
    TIPO_OPERACAO = (
        ('Entrada', 'Entrada'),
        ('Saída', 'Saída'),
        ('Ajuste', 'Ajuste'),
        ('Lote Criado', 'Lote Criado'),
        ('Lote Excluído', 'Lote Excluído'),
    )

    
    variacao = models.ForeignKey(VariacaoProduto, on_delete=models.PROTECT, related_name='historico')
    lote = models.ForeignKey(Lote, on_delete=models.SET_NULL, related_name='historico', null=True, blank=True)
    quantidade_anterior = models.DecimalField(max_digits=20, decimal_places=4)
    quantidade_nova = models.DecimalField(max_digits=20, decimal_places=4)
    tipo_operacao = models.CharField(max_length=20, choices=TIPO_OPERACAO)
    motivo = models.TextField()
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Histórico de Estoque'
        verbose_name_plural = 'Históricos de Estoque'

    def __str__(self):
        return f"{self.variacao.produto.nome} - {self.tipo_operacao} - {self.created_at|date:'d/m/Y H:i'}"