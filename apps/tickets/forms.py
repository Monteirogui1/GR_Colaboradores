from django import forms
from django.core.exceptions import ValidationError
from .models import (
    Ticket, AcaoTicket, AnexoTicket,
    Categoria, Urgencia, Status, Justificativa, Servico,
    ContratoSLA, RegraSLA, CampoAdicional, RegraExibicaoCampo,
    Gatilho, Macro, StatusBase
)
from apps.authentication.models import User

# ==================== CLASSIFICAÇÕES ====================

class CategoriaForm(forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ['nome', 'descricao', 'disponivel_para', 'ativo']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'descricao': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'disponivel_para': forms.Select(attrs={'class': 'form-control'}),
            'ativo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class UrgenciaForm(forms.ModelForm):
    class Meta:
        model = Urgencia
        fields = ['nome', 'nivel', 'cor', 'ativo']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'nivel': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 10}),
            'cor': forms.TextInput(attrs={'class': 'form-control', 'type': 'color'}),
            'ativo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class StatusForm(forms.ModelForm):
    class Meta:
        model = Status
        fields = ['nome', 'status_base', 'requer_justificativa', 'disponivel_para', 'cor', 'ordem', 'ativo']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'status_base': forms.Select(attrs={'class': 'form-control'}),
            'requer_justificativa': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'disponivel_para': forms.Select(attrs={'class': 'form-control'}),
            'cor': forms.TextInput(attrs={'class': 'form-control', 'type': 'color'}),
            'ordem': forms.NumberInput(attrs={'class': 'form-control'}),
            'ativo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Se editando, bloqueia alteração do status_base
        if self.instance.pk:
            self.fields['status_base'].disabled = True
            self.fields['status_base'].help_text = "Status base não pode ser alterado após criação"


class JustificativaForm(forms.ModelForm):
    class Meta:
        model = Justificativa
        fields = ['nome', 'descricao', 'ativo']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'descricao': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'ativo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class ServicoForm(forms.ModelForm):
    class Meta:
        model = Servico
        fields = ['nome', 'descricao', 'ativo']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'descricao': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'ativo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


# ==================== SLA ====================

class ContratoSLAForm(forms.ModelForm):
    class Meta:
        model = ContratoSLA
        fields = ['nome', 'descricao', 'is_padrao', 'ativo']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'descricao': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'is_padrao': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'ativo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class RegraSLAForm(forms.ModelForm):
    class Meta:
        model = RegraSLA
        fields = [
            'nome', 'ordem', 'categorias', 'urgencias', 'servicos',
            'status_pausam', 'justificativas_pausam',
            'prazo_primeira_resposta', 'prazo_solucao', 'limite_acoes_publicas',
            'tipo_horario', 'ativo'
        ]
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'ordem': forms.NumberInput(attrs={'class': 'form-control'}),
            'categorias': forms.SelectMultiple(attrs={'class': 'form-control', 'size': 5}),
            'urgencias': forms.SelectMultiple(attrs={'class': 'form-control', 'size': 5}),
            'servicos': forms.SelectMultiple(attrs={'class': 'form-control', 'size': 5}),
            'status_pausam': forms.SelectMultiple(attrs={'class': 'form-control', 'size': 5}),
            'justificativas_pausam': forms.SelectMultiple(attrs={'class': 'form-control', 'size': 5}),
            'prazo_primeira_resposta': forms.NumberInput(attrs={'class': 'form-control'}),
            'prazo_solucao': forms.NumberInput(attrs={'class': 'form-control'}),
            'limite_acoes_publicas': forms.NumberInput(attrs={'class': 'form-control'}),
            'tipo_horario': forms.Select(attrs={'class': 'form-control'}),
            'ativo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


# ==================== CAMPOS ADICIONAIS ====================

class CampoAdicionalForm(forms.ModelForm):
    class Meta:
        model = CampoAdicional
        fields = [
            'nome', 'tipo', 'descricao', 'opcoes',
            'multipla_selecao', 'casas_decimais', 'expressao_regular', 'ativo'
        ]
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'tipo': forms.Select(attrs={'class': 'form-control'}),
            'descricao': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'opcoes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 5,
                'placeholder': '["Opção 1", "Opção 2", "Opção 3"]'
            }),
            'multipla_selecao': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'casas_decimais': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'max': 10}),
            'expressao_regular': forms.TextInput(attrs={'class': 'form-control'}),
            'ativo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class RegraExibicaoCampoForm(forms.ModelForm):
    class Meta:
        model = RegraExibicaoCampo
        fields = [
            'nome', 'campo', 'condicoes', 'colunas', 'exibir_para',
            'obrigatoriedade', 'condicoes_obrigatoriedade', 'ordem', 'ativo'
        ]
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'campo': forms.Select(attrs={'class': 'form-control'}),
            'condicoes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 5,
                'placeholder': '{"categoria": 1, "urgencia": 2}'
            }),
            'colunas': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 12}),
            'exibir_para': forms.Select(attrs={'class': 'form-control'}),
            'obrigatoriedade': forms.Select(attrs={'class': 'form-control'}),
            'condicoes_obrigatoriedade': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': '{"status": "resolvido"}'
            }),
            'ordem': forms.NumberInput(attrs={'class': 'form-control'}),
            'ativo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


# ==================== TICKET ====================

class TicketForm(forms.ModelForm):
    """Formulário principal de criação/edição de ticket"""

    class Meta:
        model = Ticket
        fields = [
            'solicitante', 'status', 'categoria', 'urgencia', 'servico',
            'justificativa', 'responsavel', 'assunto', 'descricao',
            'tipo_ticket', 'tags', 'cc', 'ticket_pai'
        ]
        widgets = {
            'solicitante': forms.Select(attrs={'class': 'form-control', 'required': True}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'categoria': forms.Select(attrs={'class': 'form-control'}),
            'urgencia': forms.Select(attrs={'class': 'form-control'}),
            'servico': forms.Select(attrs={'class': 'form-control'}),
            'justificativa': forms.Select(attrs={'class': 'form-control'}),
            'responsavel': forms.Select(attrs={'class': 'form-control'}),
            'assunto': forms.TextInput(attrs={'class': 'form-control'}),
            'descricao': forms.Textarea(attrs={'class': 'form-control', 'rows': 5,}),
            'tipo_ticket': forms.Select(attrs={'class': 'form-control'}),
            'tags': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'tag1, tag2, tag3'
            }),
            'cc': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'email1@example.com, email2@example.com'
            }),
            'ticket_pai': forms.Select(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        self.usuario = kwargs.pop('usuario', None)
        super().__init__(*args, **kwargs)

        # Filtra urgências baseado na categoria selecionada
        if self.instance.pk and self.instance.categoria:
            urgencias_ids = self.instance.categoria.urgencias_permitidas.values_list('urgencia_id', flat=True)
            self.fields['urgencia'].queryset = Urgencia.objects.filter(id__in=urgencias_ids, ativo=True)

        # Configura obrigatoriedade de justificativa
        if self.instance.pk and self.instance.status and self.instance.status.requer_justificativa:
            self.fields['justificativa'].required = True
        else:
            self.fields['justificativa'].required = False

        # Filtra dados por cliente se usuario fornecido
        if self.usuario:
            cliente = self.usuario if self.usuario.is_staff else self.usuario

            self.fields['categoria'].queryset = Categoria.objects.filter(cliente=cliente, ativo=True)
            self.fields['urgencia'].queryset = Urgencia.objects.filter(cliente=cliente, ativo=True)
            self.fields['status'].queryset = Status.objects.filter(cliente=cliente, ativo=True)
            self.fields['servico'].queryset = Servico.objects.filter(cliente=cliente, ativo=True)
            self.fields['justificativa'].queryset = Justificativa.objects.filter(cliente=cliente, ativo=True)

    def clean(self):
        cleaned_data = super().clean()
        categoria = cleaned_data.get('categoria')
        urgencia = cleaned_data.get('urgencia')
        status = cleaned_data.get('status')
        justificativa = cleaned_data.get('justificativa')

        # Valida urgência vs categoria
        if categoria and urgencia:
            if categoria.urgencias_permitidas.exists():
                if not categoria.urgencias_permitidas.filter(urgencia=urgencia).exists():
                    raise ValidationError(
                        f"A urgência '{urgencia}' não é permitida para a categoria '{categoria}'"
                    )

        # Valida justificativa obrigatória
        if status and status.requer_justificativa and not justificativa:
            raise ValidationError(
                f"O status '{status}' requer uma justificativa"
            )

        # Processa tags
        tags_input = cleaned_data.get('tags')
        if isinstance(tags_input, str):
            cleaned_data['tags'] = [tag.strip() for tag in tags_input.split(',') if tag.strip()]

        # Processa CC
        cc_input = cleaned_data.get('cc')
        if isinstance(cc_input, str):
            cleaned_data['cc'] = [email.strip() for email in cc_input.split(',') if email.strip()]

        return cleaned_data


class TicketFiltroForm(forms.Form):
    """Formulário de filtros para listagem de tickets"""

    numero = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Número do ticket'})
    )
    solicitante = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nome do solicitante'})
    )
    assunto = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Assunto'})
    )
    status = forms.ModelChoiceField(
        queryset=Status.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    categoria = forms.ModelChoiceField(
        queryset=Categoria.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    urgencia = forms.ModelChoiceField(
        queryset=Urgencia.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    responsavel = forms.ModelChoiceField(
        queryset=None,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    data_inicio = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    data_fim = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    nao_concluidos = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label="Apenas não concluídos"
    )

    def __init__(self, *args, **kwargs):
        usuario = kwargs.pop('usuario', None)
        super().__init__(*args, **kwargs)

        if usuario:
            cliente = usuario if usuario.is_staff else usuario

            self.fields['status'].queryset = Status.objects.filter(cliente=cliente, ativo=True)
            self.fields['categoria'].queryset = Categoria.objects.filter(cliente=cliente, ativo=True)
            self.fields['urgencia'].queryset = Urgencia.objects.filter(cliente=cliente, ativo=True)
            self.fields['responsavel'].queryset = User.objects.filter(is_staff=True, is_active=True)


class AcaoTicketForm(forms.ModelForm):
    """Formulário para adicionar ação no ticket"""

    aplicar_macro = forms.ModelChoiceField(
        queryset=Macro.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Aplicar Macro (opcional)"
    )

    class Meta:
        model = AcaoTicket
        fields = ['tipo', 'conteudo', 'tempo_trabalhado']
        widgets = {
            'tipo': forms.Select(attrs={'class': 'form-control'}),
            'conteudo': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 5,
                'placeholder': 'Descreva a ação...'
            }),
            'tempo_trabalhado': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'HH:MM:SS (opcional)'
            }),
        }

    def __init__(self, *args, **kwargs):
        usuario = kwargs.pop('usuario', None)
        super().__init__(*args, **kwargs)

        if usuario:
            cliente = usuario if usuario.is_staff else usuario
            self.fields['aplicar_macro'].queryset = Macro.objects.filter(cliente=cliente, ativo=True)


class AnexoTicketForm(forms.ModelForm):
    """Formulário para upload de anexos"""

    class Meta:
        model = AnexoTicket
        fields = ['arquivo']
        widgets = {
            'arquivo': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': '*/*'
            }),
        }

    def clean_arquivo(self):
        arquivo = self.cleaned_data.get('arquivo')

        if arquivo:
            # Valida tamanho máximo (25MB)
            if arquivo.size > 25 * 1024 * 1024:
                raise ValidationError("O arquivo não pode exceder 25MB")

        return arquivo


# ==================== AUTOMAÇÕES ====================

class GatilhoForm(forms.ModelForm):
    class Meta:
        model = Gatilho
        fields = ['nome', 'descricao', 'condicoes', 'acoes', 'ordem', 'ativo']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'descricao': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'condicoes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 8,
                'placeholder': '{"campo": "status", "operador": "igual", "valor": "resolvido"}'
            }),
            'acoes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 8,
                'placeholder': '{"acao": "enviar_email", "destinatario": "solicitante"}'
            }),
            'ordem': forms.NumberInput(attrs={'class': 'form-control'}),
            'ativo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class MacroForm(forms.ModelForm):
    class Meta:
        model = Macro
        fields = ['nome', 'descricao', 'acoes', 'ativo']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'descricao': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'acoes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 8,
                'placeholder': '{"status": 2, "responsavel": 1, "adicionar_acao": "Resolvido conforme solicitado"}'
            }),
            'ativo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


# ==================== AÇÕES RÁPIDAS ====================

class AlterarStatusForm(forms.Form):
    """Formulário rápido para alterar status"""
    status = forms.ModelChoiceField(
        queryset=Status.objects.none(),
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Novo Status"
    )
    justificativa = forms.ModelChoiceField(
        queryset=Justificativa.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Justificativa"
    )
    adicionar_acao = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Comentário sobre a mudança (opcional)'
        }),
        label="Adicionar comentário"
    )

    def __init__(self, *args, **kwargs):
        usuario = kwargs.pop('usuario', None)
        ticket = kwargs.pop('ticket', None)
        super().__init__(*args, **kwargs)

        if usuario:
            cliente = usuario if usuario.is_staff else usuario
            self.fields['status'].queryset = Status.objects.filter(cliente=cliente, ativo=True)
            self.fields['justificativa'].queryset = Justificativa.objects.filter(cliente=cliente, ativo=True)


class AlterarResponsavelForm(forms.Form):
    """Formulário rápido para alterar responsável"""
    responsavel = forms.ModelChoiceField(
        queryset=None,
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Novo Responsável"
    )
    notificar = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label="Notificar novo responsável"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['responsavel'].queryset = User.objects.filter(is_staff=True, is_active=True)


class MesclarTicketsForm(forms.Form):
    """Formulário para mesclar tickets"""
    tickets_mesclar = forms.ModelMultipleChoiceField(
        queryset=Ticket.objects.none(),
        widget=forms.CheckboxSelectMultiple(),
        label="Selecione os tickets para mesclar"
    )

    def __init__(self, *args, **kwargs):
        ticket_principal = kwargs.pop('ticket_principal', None)
        usuario = kwargs.pop('usuario', None)
        super().__init__(*args, **kwargs)

        if ticket_principal and usuario:
            # Não permite mesclar tickets fechados
            self.fields['tickets_mesclar'].queryset = Ticket.objects.filter(
                cliente=usuario if usuario.is_staff else usuario
            ).exclude(
                status__status_base=StatusBase.FECHADO
            ).exclude(
                pk=ticket_principal.pk
            )

    def clean_tickets_mesclar(self):
        tickets = self.cleaned_data.get('tickets_mesclar')

        if not tickets:
            raise ValidationError("Selecione pelo menos um ticket para mesclar")

        # Verifica se algum ticket está fechado
        for ticket in tickets:
            if ticket.status.status_base == StatusBase.FECHADO:
                raise ValidationError(
                    f"Não é possível mesclar o ticket #{ticket.numero} porque ele está fechado"
                )

        return tickets


class ReabrirTicketForm(forms.Form):
    """Formulário para reabrir ticket"""
    motivo = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Motivo da reabertura...'
        }),
        label="Motivo"
    )
    novo_status = forms.ModelChoiceField(
        queryset=Status.objects.none(),
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Status após reabertura"
    )

    def __init__(self, *args, **kwargs):
        usuario = kwargs.pop('usuario', None)
        super().__init__(*args, **kwargs)

        if usuario:
            cliente = usuario if usuario.is_staff else usuario
            # Apenas status que não sejam fechado, resolvido ou cancelado
            self.fields['novo_status'].queryset = Status.objects.filter(
                cliente=cliente,
                ativo=True
            ).exclude(
                status_base__in=[StatusBase.FECHADO, StatusBase.RESOLVIDO, StatusBase.CANCELADO]
            )


class AlterarPrevisaoSLAForm(forms.Form):
    """Formulário para alterar previsão de solução manualmente"""
    previsao_solucao = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={
            'class': 'form-control',
            'type': 'datetime-local'
        }),
        label="Nova Previsão de Solução"
    )
    motivo = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Motivo da alteração (opcional)'
        }),
        label="Motivo"
    )