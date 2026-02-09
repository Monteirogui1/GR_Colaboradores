from django import forms
from .models import Lote, Movimentacao, HistoricoEstoque, TipoMovimentacao
from ..produtos.models import VariacaoProduto


class LoteForm(forms.ModelForm):
    class Meta:
        model = Lote
        fields = [
            'variacao',
            'numero_lote',
            'quantidade',
            'preco_unitario',
            'documento_nfe'
        ]
        labels = {
            'variacao': 'Produto/Variação',
            'numero_lote': 'Número do Lote',
            'quantidade': 'Quantidade',
            'preco_unitario': 'Preço Unitário',
            'documento_nfe': 'Nota Fiscal (XML ou PDF)',
        }
        widgets = {
            'variacao': forms.Select(attrs={'class': 'form-control'}),
            'numero_lote': forms.TextInput(attrs={'class': 'form-control'}),
            'quantidade': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'preco_unitario': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'documento_nfe': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }
        help_texts = {
            'quantidade': 'Informe a quantidade total deste lote.',
            'documento_nfe': 'Anexe a nota fiscal correspondente ao lote, se houver.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['variacao'].queryset = VariacaoProduto.objects.select_related('produto').filter(produto__status=True)

    def clean_numero_lote(self):
        numero_lote = self.cleaned_data.get('numero_lote')
        if not numero_lote.strip():
            raise forms.ValidationError("O número do lote não pode estar vazio.")
        if Lote.objects.filter(numero_lote=numero_lote).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Este número de lote já está em uso.")
        return numero_lote

    def clean_quantidade(self):
        quantidade = self.cleaned_data.get('quantidade')
        if quantidade <= 0:
            raise forms.ValidationError("A quantidade deve ser maior que zero.")
        return quantidade


class MovimentacaoForm(forms.ModelForm):
    class Meta:
        model = Movimentacao
        fields = [
            'tipo',
            'variacao',
            'quantidade',
            'lote',
            'observacao',
        ]
        labels = {
            'tipo': 'Tipo de Movimentação',
            'variacao': 'Produto/Variação',
            'quantidade': 'Quantidade',
            'lote': 'Lote (opcional)',
            'observacao': 'Observação',
        }
        widgets = {
            'tipo': forms.Select(attrs={'class': 'form-control'}),
            'variacao': forms.Select(attrs={'class': 'form-control'}),
            'quantidade': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'lote': forms.Select(attrs={'class': 'form-control'}),
            'observacao': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }
        help_texts = {
            'quantidade': 'Informe a quantidade a ser movimentada (unidade do produto selecionado).',
            'lote': 'Selecione um lote se desejar vincular a movimentação.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Exibe apenas variações e lotes ativos. Ajuste o filtro se precisar!
        self.fields['variacao'].queryset = VariacaoProduto.objects.select_related('produto').filter(produto__status=True)
        self.fields['lote'].queryset = Lote.objects.all()
        self.fields['tipo'].queryset = TipoMovimentacao.objects.all()
    def clean_quantidade(self):
        quantidade = self.cleaned_data.get('quantidade')
        tipo = self.cleaned_data.get('tipo')
        if tipo != 'Ajuste' and quantidade <= 0:
            raise forms.ValidationError("A quantidade deve ser maior que zero para Entrada ou Saída.")
        return quantidade


class HistoricoEstoqueForm(forms.ModelForm):
    class Meta:
        model = Movimentacao
        fields = ['variacao', 'quantidade', 'observacao']
        labels = {
            'variacao': 'Variação do Produto',
            'quantidade': 'Nova Quantidade',
            'observacao': 'Motivo do Ajuste',
        }
        widgets = {
            'variacao': forms.Select(attrs={'class': 'form-control', 'autofocus': True}),
            'quantidade': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Ex.: 100'}),
            'observacao': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Motivo do ajuste'}),
        }

    def clean_quantidade(self):
        quantidade = self.cleaned_data.get('quantidade')
        if quantidade < 0:
            raise forms.ValidationError("A quantidade não pode ser negativa.")
        return quantidade


class TipoMovimentacaoForm(forms.ModelForm):
    class Meta:
        model = TipoMovimentacao
        fields = ['nome', 'entrada_saida', 'descricao']
        labels = {
            'nome': 'Nome do Tipo',
            'entrada_saida': 'Entrada ou Saída?',
            'descricao': 'Descrição',
        }
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'descricao': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
            'entrada_saida': forms.Select(attrs={'class': 'form-control'})
        }

class ImportacaoMovimentacaoForm(forms.Form):
    arquivo = forms.FileField(
        label='Arquivo CSV/Excel/XML',
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'}),
        help_text='Importe um arquivo contendo as movimentações/lotes em massa.'
    )