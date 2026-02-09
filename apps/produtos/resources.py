from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget
from .models import Produto, VariacaoProduto
from apps.categorias.models import Categoria
from apps.marcas.models import Marca
from apps.fornecedor.models import Fornecedor

class ProdutoResource(resources.ModelResource):
    categoria = fields.Field(
        column_name='categoria',
        attribute='categoria',
        widget=ForeignKeyWidget(Categoria, field='nome')
    )
    marca = fields.Field(
        column_name='marca',
        attribute='marca',
        widget=ForeignKeyWidget(Marca, field='nome')
    )
    fornecedor = fields.Field(
        column_name='fornecedor',
        attribute='fornecedor',
        widget=ForeignKeyWidget(Fornecedor, field='nome')
    )

    class Meta:
        model = Produto
        fields = ('nome', 'status', 'categoria', 'marca', 'fornecedor', 'num_serie',
                  'preco_custo', 'preco_venda', 'descricao', 'estoque_minimo', 'quantidade')
        export_order = fields
        import_id_fields = ('num_serie',)  # Identifica registros por  número de série

class VariacaoProdutoResource(resources.ModelResource):
    produto = fields.Field(
        column_name='produto',
        attribute='produto',
        widget=ForeignKeyWidget(Produto, field='nome')
    )

    class Meta:
        model = VariacaoProduto
        fields = ('produto', 'tamanho', 'quantidade', 'estoque_minimo', 'codigo_barras')
        export_order = fields
        import_id_fields = ('codigo_barras',)