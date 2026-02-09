from django.db.models.signals import post_save
from django.dispatch import receiver
from apps.produtos.models import VariacaoProduto
from apps.notificacao.models import Notificacao
from .utils import enviar_email_estoque_minimo

@receiver(post_save, sender=VariacaoProduto)
def verificar_estoque_minimo(sender, instance, created,**kwargs):
    if created:
        return
    # Só alerta se estiver igual ou abaixo do mínimo e não tiver notificação não lida
    if instance.quantidade <= instance.estoque_minimo:
        not_exist = not Notificacao.objects.filter(
            produto=instance.produto,
            mensagem__icontains=instance.tamanho,
            lida=False
        ).exists()
        if not_exist:
            mensagem = (
                f"O produto '{instance.produto.nome}' (Tamanho: {instance.tamanho}) "
                f"atingiu o estoque mínimo ({instance.quantidade}/{instance.estoque_minimo})!"
            )
            Notificacao.objects.create(
                produto=instance.produto,
                mensagem=mensagem
            )
            enviar_email_estoque_minimo(instance)
