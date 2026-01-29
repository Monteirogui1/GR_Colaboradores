from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from apps.ativos.models import AtivoUtilizador, AtivoHistorico
from .models import Ativo

@receiver(post_save, sender=Ativo)
def criar_historico_criacao(sender, instance, created, **kwargs):
    """Cria histórico quando um ativo é criado"""
    if created:
        AtivoHistorico.objects.create(
            ativo=instance,
            descricao=f"Ativo criado: {instance.nome}",
            usuario=None  # Será definido na view
        )


@receiver(pre_save, sender=Ativo)
def registrar_alteracoes(sender, instance, **kwargs):
    """Registra as alterações nos campos do ativo"""
    if instance.pk:  # Só para updates, não para criação
        try:
            ativo_anterior = Ativo.objects.get(pk=instance.pk)

            # Lista de campos a monitorar
            campos_monitorados = {
                'nome': 'Nome',
                'etiqueta': 'Etiqueta',
                'numero_serie': 'Número de Série',
                'codigo_referencia': 'Código Referência',
                'categoria': 'Categoria',
                'fornecedor': 'Fornecedor',
                'localizacao': 'Localização',
                'marca': 'Marca',
                'computador': 'Computador',
                'status': 'Status',
                'fabricante': 'Fabricante',
                'modelo': 'Modelo',
                'data_compra': 'Data de Compra',
                'garantia_ate': 'Garantia Até',
                'custo': 'Custo',
                'descricao': 'Descrição',
                'auditoria': 'Auditoria',
            }

            # Armazena as alterações para criar histórico depois
            instance._alteracoes = []

            for campo, nome_campo in campos_monitorados.items():
                valor_antigo = getattr(ativo_anterior, campo)
                valor_novo = getattr(instance, campo)

                # Converte objetos relacionados para string
                if hasattr(valor_antigo, '__str__'):
                    valor_antigo_str = str(valor_antigo) if valor_antigo else '-'
                else:
                    valor_antigo_str = valor_antigo if valor_antigo else '-'

                if hasattr(valor_novo, '__str__'):
                    valor_novo_str = str(valor_novo) if valor_novo else '-'
                else:
                    valor_novo_str = valor_novo if valor_novo else '-'

                if valor_antigo != valor_novo:
                    instance._alteracoes.append({
                        'campo': nome_campo,
                        'campo_db': campo,
                        'anterior': valor_antigo_str,
                        'novo': valor_novo_str
                    })
        except Ativo.DoesNotExist:
            pass


@receiver(post_save, sender=Ativo)
def salvar_historico_alteracoes(sender, instance, created, **kwargs):
    """Salva o histórico das alterações após salvar o ativo"""
    if not created and hasattr(instance, '_alteracoes') and instance._alteracoes:
        for alteracao in instance._alteracoes:
            AtivoHistorico.objects.create(
                ativo=instance,
                campo_alterado=alteracao['campo'],
                valor_anterior=alteracao['anterior'],
                valor_novo=alteracao['novo'],
                descricao=f"{alteracao['campo']} alterado de '{alteracao['anterior']}' para '{alteracao['novo']}'",
                usuario=None  # Será definido na view se possível
            )


@receiver(post_save, sender=AtivoUtilizador)
def criar_historico_utilizador(sender, instance, created, **kwargs):
    """Cria histórico quando um utilizador é atribuído"""
    if created:
        AtivoHistorico.objects.create(
            ativo=instance.ativo,
            descricao=f"Ativo atribuído a {instance.usuario.get_full_name() or instance.usuario.username}",
            usuario=None
        )