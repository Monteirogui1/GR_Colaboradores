from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db import transaction
from import_export.signals import post_import
from apps.produtos.models import VariacaoProduto
from .models import Movimentacao, Lote, HistoricoEstoque
from ..notificacao.models import Notificacao
from apps.produtos.resources import VariacaoProdutoResource
from decimal import Decimal
from ..notificacao.utils import enviar_email_estoque_minimo

FATORES = {
    'UN': Decimal('1'),
    'ML': Decimal('0.001'),
    'L':  Decimal('1'),
    'KG': Decimal('1'),
    'GR': Decimal('0.001'),
}

def notificar_estoque_minimo(variacao):
    if variacao.quantidade <= variacao.estoque_minimo:
        mensagem = (
            f"O produto {variacao.produto.nome} ({variacao.tamanho}) está com estoque baixo: "
            f"{variacao.quantidade} unidades (limite: {variacao.estoque_minimo})."
        )
        Notificacao.objects.create(produto=variacao.produto, mensagem=mensagem)
        enviar_email_estoque_minimo(variacao)

@receiver(post_save, sender=Movimentacao)
def movimentacao_update_estoque(sender, instance, created, **kwargs):
    if not created or instance.quantidade == 0:
        return

    variacao = instance.variacao
    unidade = getattr(variacao, 'unidade', 'UN')
    fator = FATORES.get(unidade, Decimal('1'))
    q_base = (instance.quantidade * fator).quantize(Decimal('0.01'))

    with transaction.atomic():
        antes = variacao.quantidade

        entrada_saida = getattr(instance.tipo, 'entrada_saida', instance.tipo)
        if entrada_saida == 'Entrada':
            variacao.quantidade += q_base
            motivo = f"Entrada de {instance.quantidade}{unidade}"
        elif entrada_saida == 'Saída':
            if variacao.quantidade < q_base:
                raise ValueError("Estoque insuficiente para esta saída")
            variacao.quantidade -= q_base
            motivo = f"Saída de {instance.quantidade}{unidade}"
        else:
            motivo = f"{entrada_saida} de {instance.quantidade}{unidade}"
            variacao.quantidade = q_base

        variacao.save()

        HistoricoEstoque.objects.create(
            variacao=variacao,
            lote=getattr(instance, 'lote', None),
            quantidade_anterior=antes,
            quantidade_nova=variacao.quantidade,
            tipo_operacao=entrada_saida,
            motivo=motivo,
            usuario=getattr(instance, 'usuario', None)
        )

        notificar_estoque_minimo(variacao)

@receiver(post_save, sender=Lote)
def lote_update_estoque(sender, instance, created, **kwargs):
    if not created:
        return
    with transaction.atomic():
        variacao = instance.variacao
        quantidade_anterior = variacao.quantidade
        variacao.quantidade += instance.quantidade
        variacao.save()

        HistoricoEstoque.objects.create(
            variacao=variacao,
            lote=instance,
            quantidade_anterior=quantidade_anterior,
            quantidade_nova=variacao.quantidade,
            tipo_operacao='Lote Criado',
            motivo=f"Criação de lote {instance.numero_lote} com {instance.quantidade} unidades.",
            usuario=getattr(instance, 'usuario', None)
        )
        notificar_estoque_minimo(variacao)

@receiver(post_delete, sender=Lote)
def lote_reverter_estoque(sender, instance, **kwargs):
    with transaction.atomic():
        variacao = instance.variacao
        quantidade_anterior = variacao.quantidade
        variacao.quantidade -= instance.quantidade
        if variacao.quantidade < 0:
            variacao.quantidade = 0
        variacao.save()

        HistoricoEstoque.objects.create(
            variacao=variacao,
            lote=instance,
            quantidade_anterior=quantidade_anterior,
            quantidade_nova=variacao.quantidade,
            tipo_operacao='Lote Excluído',
            motivo=f"Exclusão de lote {instance.numero_lote} com {instance.quantidade} unidades.",
            usuario=None
        )
        notificar_estoque_minimo(variacao)

@receiver(post_import, sender=VariacaoProdutoResource)
def post_import_variacao(model, **kwargs):
    for instance in VariacaoProduto.objects.all():
        notificar_estoque_minimo(instance)
