from django import forms
from .models import Produto, VariacaoProduto, UnidadeMedida, CampoDinamico, ProdutoComposicao, ParametroEstoque


class ProdutoForm(forms.ModelForm):
    class Meta:
        model = Produto
        fields = ['nome', 'status', 'categoria', 'marca', 'fornecedor',
                  'descricao', 'num_serie', 'preco_custo', 'preco_venda', 'imagem']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'categoria': forms.Select(attrs={'class': 'form-control'}),
            'marca': forms.Select(attrs={'class': 'form-control'}),
            'fornecedor': forms.Select(attrs={'class': 'form-control'}),
            'descricao': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'num_serie': forms.TextInput(attrs={'class': 'form-control'}),
            'preco_custo': forms.NumberInput(attrs={'class': 'form-control'}),
            'preco_venda': forms.NumberInput(attrs={'class': 'form-control'}),
            'imagem': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
        }
        labels = {
            'nome': 'Nome',
            'status': 'Status',
            'categoria': 'Categoria',
            'marca': 'Marca',
            'fornecedor': 'Fornecedor',
            'descricao': 'Descrição',
            'num_serie': 'Número de Série',
            'preco_custo': 'Preço de Custo',
            'preco_venda': 'Preço de Venda',
            'imagem': 'Imagem do Produto',
        }
        help_texts = {
            'imagem': 'Imagem principal do produto.',
        }

class VariacaoProdutoForm(forms.ModelForm):
    class Meta:
        model = VariacaoProduto
        fields = ['tamanho', 'estoque_minimo', 'codigo_barras', 'unidade']
        widgets = {
            'unidade': forms.Select(attrs={'class': 'form-control'}),
            'tamanho': forms.TextInput(attrs={'class': 'form-control'}),
            'estoque_minimo': forms.NumberInput(attrs={'class': 'form-control'}),
            'codigo_barras': forms.TextInput(attrs={'class': 'form-control'}),
        }

        labels = {
            'tamanho': 'Tamanho',
            'estoque_minimo': 'Estoque Mínimo',
            'codigo_barras': 'Código de Barras'
        }
        help_texts = {
            'tamanho': 'Exemplo: P, M, G, 500ml, Azul.',
        }

from django.forms import inlineformset_factory

VariacaoProdutoFormSet = inlineformset_factory(
    Produto, VariacaoProduto,
    form=VariacaoProdutoForm,
    extra=1, can_delete=True, min_num=0, validate_min=True
)

class UnidadeMedidaForm(forms.ModelForm):
    class Meta:
        model = UnidadeMedida
        fields = ['nome', 'sigla']
        labels = {
            'nome': 'Nome da Unidade',
            'sigla': 'Sigla (ex: UN, KG, L)',
        }
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'sigla': forms.TextInput(attrs={'class': 'form-control', 'maxlength': 10}),
        }

class CampoDinamicoForm(forms.ModelForm):
    class Meta:
        model = CampoDinamico
        fields = ['nome', 'categoria', 'tipo', 'obrigatorio']
        labels = {
            'nome': 'Nome do Campo',
            'categoria': 'Categoria',
            'tipo': 'Tipo do Campo',
            'obrigatorio': 'Obrigatório?',
        }
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'obrigatorio': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'tipo': forms.Select(attrs={'class': 'form-control'}),
            'categoria': forms.Select(attrs={'class': 'form-control'}),
        }


class ProdutoComposicaoForm(forms.ModelForm):
    class Meta:
        model = ProdutoComposicao
        fields = ['produto_componente', 'quantidade']

        widgets = {
            'produto_componente': forms.Select(attrs={'class': 'form-control'}),
            'quantidade': forms.NumberInput(attrs={'class': 'form-control'}),
        }

        labels = {
            'produto_componente': 'Componente do Produto',
            'quantidade': 'Quantidade do Produto',
        }

ProdutoComposicaoFormSet = inlineformset_factory(
    Produto,
    ProdutoComposicao,
    form=ProdutoComposicaoForm,
    extra=1, can_delete=True,
    fk_name='produto_pai'
)


class ParametroEstoqueForm(forms.ModelForm):
    class Meta:
        model = ParametroEstoque
        fields = ['estoque_minimo', 'estoque_maximo', 'alerta_reposicao']

        widgets = {
            'estoque_minimo': forms.NumberInput(attrs={'class': 'form-control'}),
            'estoque_maximo': forms.NumberInput(attrs={'class': 'form-control'}),
            'alerta_reposicao': forms.CheckboxInput(attrs={'class': 'form-control'}),
        }

        labels = {
            'estoque_minimo': 'Componente do Produto',
            'estoque_maximo': 'Quantidade do Produto',
            'alerta_reposicao': 'Alerta do Produto',
        }