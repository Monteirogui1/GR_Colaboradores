from django import forms
from .models import Ativo, Localizacao, AtivoUtilizador, AtivoAnexo, StatusAtivo


class LocalizacaoForm(forms.ModelForm):
    class Meta:
        model = Localizacao
        fields = ['nome', 'endereco', 'status']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nome da filial'}),
            'endereco': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Endereço completo'}),
            'status': forms.Select(attrs={'class': 'form-control'}, choices=((True, 'Ativo'), (False, 'Inativo'))),
        }
        labels = {
            'nome': 'Nome da Filial',
            'endereco': 'Endereço',
            'status': 'Status',
        }


class StatusAtivoForm(forms.ModelForm):
    class Meta:
        model = StatusAtivo
        fields = ['nome', 'cor', 'descricao', 'is_active']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Disponível, Em uso, Manutenção'}),
            'cor': forms.TextInput(attrs={'class': 'form-control', 'type': 'color'}),
            'descricao': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Descrição do status'}),
            'is_active': forms.Select(attrs={'class': 'form-control'}, choices=((True, 'Ativo'), (False, 'Inativo'))),
        }
        labels = {
            'nome': 'Nome do Status',
            'cor': 'Cor',
            'descricao': 'Descrição',
            'is_active': 'Ativo',
        }


class AtivoForm(forms.ModelForm):
    class Meta:
        model = Ativo
        fields = [
            'nome', 'etiqueta', 'numero_serie', 'codigo_referencia',
            'categoria', 'fornecedor', 'localizacao', 'marca', 'computador',
            'status', 'fabricante', 'modelo',
            'data_compra', 'garantia_ate', 'custo',
            'descricao', 'auditoria'
        ]
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nome do ativo'}),
            'etiqueta': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: AT-001'}),
            'numero_serie': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Número de série'}),
            'codigo_referencia': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Código de referência'}),
            'categoria': forms.Select(attrs={'class': 'form-control'}),
            'fornecedor': forms.Select(attrs={'class': 'form-control'}),
            'localizacao': forms.Select(attrs={'class': 'form-control'}),
            'marca': forms.Select(attrs={'class': 'form-control'}),
            'computador': forms.Select(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'fabricante': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Fabricante'}),
            'modelo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Modelo'}),
            'data_compra': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'garantia_ate': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'custo': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0.00', 'step': '0.01'}),
            'descricao': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Descrição do ativo'}),
            'auditoria': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Informações de auditoria'}),
        }
        labels = {
            'nome': 'Nome',
            'etiqueta': 'Etiqueta',
            'numero_serie': 'Número de Série',
            'codigo_referencia': 'Código Referência',
            'categoria': 'Categoria',
            'fornecedor': 'Fornecedor',
            'localizacao': 'Localização (Filial)',
            'marca': 'Marca',
            'computador': 'Computador',
            'status': 'Status',
            'fabricante': 'Fabricante',
            'modelo': 'Modelo',
            'data_compra': 'Data de Compra',
            'garantia_ate': 'Garantia Até',
            'custo': 'Custo (R$)',
            'descricao': 'Descrição',
            'auditoria': 'Auditoria',
        }


class AtivoUtilizadorForm(forms.ModelForm):
    class Meta:
        model = AtivoUtilizador
        fields = ['usuario', 'data_inicio', 'data_fim', 'observacoes']
        widgets = {
            'usuario': forms.Select(attrs={'class': 'form-control'}),
            'data_inicio': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'data_fim': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'observacoes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Observações'}),
        }
        labels = {
            'usuario': 'Usuário',
            'data_inicio': 'Data Início',
            'data_fim': 'Data Fim',
            'observacoes': 'Observações',
        }


class AtivoAnexoForm(forms.ModelForm):
    class Meta:
        model = AtivoAnexo
        fields = ['titulo', 'arquivo', 'descricao']
        widgets = {
            'titulo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Termo de Uso'}),
            'arquivo': forms.FileInput(attrs={'class': 'form-control'}),
            'descricao': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Descrição do arquivo'}),
        }
        labels = {
            'titulo': 'Título',
            'arquivo': 'Arquivo',
            'descricao': 'Descrição',
        }