from django.db.models.signals import post_save, pre_save, post_delete, pre_delete
from django.dispatch import receiver
from pip._internal.utils import logging

from .models import VariacaoProduto, ProdutoComposicao, ValorCampoDinamico, Produto
import barcode
from barcode.writer import ImageWriter
import qrcode
from django.core.files import File
from io import BytesIO

from ..movimentacao.models import HistoricoEstoque


def gerar_barcode_image(codigo, barcode_type):
    barcode_class = barcode.get_barcode_class(barcode_type)
    bc = barcode_class(codigo, writer=ImageWriter())
    buffer = BytesIO()
    bc.write(buffer)
    file = File(buffer)
    filename = f'barcode_{codigo}.png'
    buffer.seek(0)
    return filename, file

def gerar_qrcode_image(codigo):
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(codigo)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    file = File(buffer)
    filename = f'qrcode_{codigo}.png'
    buffer.seek(0)
    return filename, file

@receiver(pre_save, sender=VariacaoProduto)
def check_codigo_barras_change(sender, instance, **kwargs):
    instance._codigo_barras_changed = False
    if instance.pk:
        try:
            old_instance = VariacaoProduto.objects.only('codigo_barras').get(pk=instance.pk)
            if instance.codigo_barras != old_instance.codigo_barras:
                instance._codigo_barras_changed = True
        except VariacaoProduto.DoesNotExist:
            instance._codigo_barras_changed = bool(instance.codigo_barras)
    else:
        if instance.codigo_barras:
            instance._codigo_barras_changed = True

@receiver(post_save, sender=VariacaoProduto)
def gerar_codigos_produto(sender, instance, created, **kwargs):
    if getattr(instance, '_codigo_barras_changed', False) and instance.codigo_barras:
        codigo = instance.codigo_barras.strip()
        if len(codigo) == 13 and codigo.isdigit():
            barcode_type = 'ean13'
        elif len(codigo) == 8 and codigo.isdigit():
            barcode_type = 'ean8'
        elif len(codigo) == 12 and codigo.isdigit():
            barcode_type = 'upca'
        else:
            barcode_type = 'code128'

        if instance.barcode_image:
            instance.barcode_image.delete(save=False)
        if instance.qr_code:
            instance.qr_code.delete(save=False)

        alterou_img = False
        try:
            filename, file = gerar_barcode_image(codigo, barcode_type)
            instance.barcode_image.save(filename, file, save=False)
            alterou_img = True
        except Exception as e:
            print(f"[ERRO BARCODE] Código: {codigo} ({barcode_type}): {e}")

        try:
            filename, file = gerar_qrcode_image(codigo)
            instance.qr_code.save(filename, file, save=False)
            alterou_img = True
        except Exception as e:
            print(f"[ERRO QR] Código: {codigo}: {e}")

        if alterou_img:
            instance._codigo_barras_changed = False
            instance.save(update_fields=['barcode_image', 'qr_code'])


@receiver(post_save, sender=ProdutoComposicao)
def abate_estoque_ao_montar_kit(sender, instance, created, **kwargs):
    """
    Ao montar um kit, abate o estoque dos componentes conforme a quantidade definida na composição.
    """
    if created:
        produto_pai = instance.produto_pai
        for comp in ProdutoComposicao.objects.filter(produto_pai=produto_pai):
            variacao_comp = comp.produto_componente.variacoes.first()
            if variacao_comp:
                estoque_antes = variacao_comp.quantidade
                abater = comp.quantidade
                variacao_comp.quantidade = max(0, variacao_comp.quantidade - abater)
                variacao_comp.save()
                HistoricoEstoque.objects.create(
                    variacao=variacao_comp,
                    quantidade_anterior=estoque_antes,
                    quantidade_nova=variacao_comp.quantidade,
                    tipo_operacao='Kit Montado',
                    motivo=f"Montagem do kit {produto_pai.nome}, componente {variacao_comp.produto.nome}",
                    usuario=instance.request.user if hasattr(instance, 'request') else None
                )

@receiver(post_delete, sender=ProdutoComposicao)
def devolve_estoque_ao_desmontar_kit(sender, instance, **kwargs):
    """
    Ao desmontar um kit (ou desfazer a venda), devolve o estoque dos componentes.
    """
    produto_pai = instance.produto_pai
    variacao_comp = instance.produto_componente.variacoes.first()
    if variacao_comp:
        estoque_antes = variacao_comp.quantidade
        variacao_comp.quantidade += instance.quantidade
        variacao_comp.save()
        HistoricoEstoque.objects.create(
            variacao=variacao_comp,
            quantidade_anterior=estoque_antes,
            quantidade_nova=variacao_comp.quantidade,
            tipo_operacao='Kit Desfeito',
            motivo=f"Desmontagem do kit {produto_pai.nome}, componente {variacao_comp.produto.nome}",
            usuario=instance.request.user if hasattr(instance, 'request') else None  # Associe com request.user se disponível
        )

