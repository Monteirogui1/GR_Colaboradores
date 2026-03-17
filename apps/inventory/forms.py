from django import forms
from .models import Machine, MachineGroup, BlockedSite, Notification, AgentVersion


class MachineForm(forms.ModelForm):
    class Meta:
        model = Machine
        fields = [
            'hostname', 'ip_address', 'mac_address', 'group',
            'manufacturer', 'model', 'serial_number',
            'cpu', 'ram_gb', 'disk_space_gb', 'disk_free_gb',
            'os_caption', 'os_architecture', 'os_build',
            'gpu_name', 'antivirus_name'
        ]
        widgets = {
            'hostname': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nome da máquina'}),
            'ip_address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 192.168.1.100'}),
            'mac_address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: AA:BB:CC:DD:EE:FF'}),
            'group': forms.Select(attrs={'class': 'form-control'}),
            'manufacturer': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Fabricante'}),
            'model': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Modelo'}),
            'serial_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Número de série'}),
            'cpu': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Processador'}),
            'ram_gb': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'GB', 'step': '0.01'}),
            'disk_space_gb': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'GB', 'step': '0.01'}),
            'disk_free_gb': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'GB', 'step': '0.01'}),
            'os_caption': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Sistema Operacional'}),
            'os_architecture': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 64-bit'}),
            'os_build': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Build do SO'}),
            'gpu_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Placa de vídeo'}),
            'antivirus_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Antivírus instalado'}),
        }


class MachineGroupForm(forms.ModelForm):
    class Meta:
        model = MachineGroup
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nome do grupo'}),
            'description': forms.Textarea(
                attrs={'class': 'form-control', 'placeholder': 'Descrição do grupo', 'rows': 3}),
        }


class BlockedSiteForm(forms.ModelForm):
    class Meta:
        model = BlockedSite
        fields = ['url', 'machine', 'group']
        widgets = {
            'url': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: facebook.com'}),
            'machine': forms.Select(attrs={'class': 'form-control'}),
            'group': forms.Select(attrs={'class': 'form-control'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        machine = cleaned_data.get('machine')
        group = cleaned_data.get('group')

        if not machine and not group:
            raise forms.ValidationError('Selecione uma máquina ou um grupo.')

        if machine and group:
            raise forms.ValidationError('Selecione apenas uma máquina OU um grupo, não ambos.')

        return cleaned_data


class NotificationForm(forms.ModelForm):
    '''Form para criar/editar notificações'''

    class Meta:
        model = Notification
        fields = [
            'machine',
            'title',
            'message',
            'type',
            'priority',
            'expires_at',
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Digite o título da notificação'
            }),
            'message': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Digite a mensagem completa'
            }),
            'type': forms.Select(attrs={
                'class': 'form-control'
            }),
            'priority': forms.Select(attrs={
                'class': 'form-control'
            }),
            'machine': forms.Select(attrs={
                'class': 'form-control'
            }),
            'expires_at': forms.DateTimeInput(attrs={
                'class': 'form-control',
                'type': 'datetime-local'
            }),
        }


class BulkNotificationForm(forms.Form):
    '''Form para criar notificações em massa'''

    machines = forms.ModelMultipleChoiceField(
        queryset=Machine.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        label='Máquinas',
        help_text='Selecione as máquinas que receberão a notificação'
    )

    title = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Título da notificação'
        })
    )

    message = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': 'Mensagem completa'
        })
    )

    type = forms.ChoiceField(
        choices=Notification.TYPE_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'}),
        initial='info'
    )

    priority = forms.ChoiceField(
        choices=Notification.PRIORITY_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'}),
        initial='normal'
    )

    expires_at = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={
            'class': 'form-control',
            'type': 'datetime-local'
        }),
        label='Expira em (opcional)'
    )


class AgentTokenGenerateForm(forms.Form):
    """
    Formulário de geração de tokens.

    Corrigido em relação à versão anterior:
    - Adicionada opção 'infinite' (sem expiração) em `days`
    - `days` agora é CharField para aceitar 'infinite' sem conflito de tipo
    - Validação de `days` movida para clean_days()
    - `quantity` com validação max_value dinâmica via __init__
    """

    DAYS_CHOICES = [
        ('infinite', 'Sem expiração'),
        ('1', '1 dia'),
        ('3', '3 dias'),
        ('7', '7 dias (recomendado)'),
        ('14', '14 dias'),
        ('30', '30 dias'),
        ('60', '60 dias'),
        ('90', '90 dias'),
        ('180', '180 dias'),
        ('365', '365 dias (1 ano)'),
    ]

    quantity = forms.IntegerField(
        label='Quantidade de Tokens',
        min_value=1,
        max_value=50,
        initial=1,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ex: 1',
            'min': '1',
            'max': '50',
        }),
        help_text='Gere até 50 tokens de uma vez',
    )

    days = forms.ChoiceField(
        label='Validade',
        choices=DAYS_CHOICES,
        initial='7',
        widget=forms.Select(attrs={'class': 'form-control'}),
        help_text='Tempo até o token expirar (máquinas já registradas não são afetadas)',
    )

    def clean_quantity(self):
        qty = self.cleaned_data.get('quantity')
        if qty is None or qty < 1 or qty > 50:
            raise forms.ValidationError('Informe uma quantidade entre 1 e 50.')
        return qty

    def clean_days(self):
        val = self.cleaned_data.get('days', '').strip()
        if val == 'infinite':
            return 'infinite'
        try:
            days = int(val)
            if days < 1 or days > 365:
                raise forms.ValidationError('Validade deve ser entre 1 e 365 dias.')
            return str(days)
        except (ValueError, TypeError):
            raise forms.ValidationError('Validade inválida.')

class AgentVersionForm(forms.ModelForm):
    """Formulário para criação/edição de versão do agente."""

    class Meta:
        model = AgentVersion
        fields = ['version', 'agent_type', 'file_path', 'release_notes', 'is_mandatory']
        widgets = {
            'version': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '3.2.0',
            }),
            'agent_type': forms.Select(attrs={
                'class': 'form-control',
            }),
            'file_path': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': '.py,.exe',
            }),
            'release_notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 6,
                'placeholder': '- Correção no update loop\n- SHA-256 adicionado\n- Suporte a agent_type',
            }),
            'is_mandatory': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
            }),
        }
        labels = {
            'version': 'Versão',
            'agent_type': 'Tipo de Agente',
            'file_path': 'Arquivo (.py em dev · .exe em produção)',
            'release_notes': 'Notas de Lançamento',
            'is_mandatory': 'Atualização Obrigatória',
        }
        help_texts = {
            'version': 'Formato MAJOR.MINOR.PATCH — ex: 3.2.0',
            'agent_type': 'service = agent_service.exe · tray = agent_tray.exe',
            'file_path': 'Tamanho máximo 50 MB',
            'release_notes': 'Descreva o que mudou nesta versão',
            'is_mandatory': 'Se marcado, todos os agentes deste tipo serão forçados a atualizar',
        }

    # ── Validações ────────────────────────────────────────────────────────────

    def clean_version(self):
        version = self.cleaned_data.get('version', '').strip()
        if not version:
            raise forms.ValidationError('Versão é obrigatória.')
        parts = version.split('.')
        if len(parts) != 3:
            raise forms.ValidationError('Use o formato MAJOR.MINOR.PATCH (ex: 3.2.0).')
        for p in parts:
            if not p.isdigit():
                raise forms.ValidationError('A versão deve conter apenas números separados por pontos.')
        return version

    def clean_file_path(self):
        file = self.cleaned_data.get('file_path')
        if file:
            ext = file.name.rsplit('.', 1)[-1].lower() if '.' in file.name else ''
            if ext not in ('py', 'exe'):
                raise forms.ValidationError('Extensão inválida. Use .py (dev) ou .exe (produção).')
            if file.size > 50 * 1024 * 1024:
                raise forms.ValidationError('Arquivo muito grande. Limite: 50 MB.')
        return file

    def clean(self):
        cleaned = super().clean()
        version = cleaned.get('version')
        agent_type = cleaned.get('agent_type')
        # Impede duplicata versão + tipo (exceto no próprio objeto em edição)
        if version and agent_type:
            qs = AgentVersion.objects.filter(version=version, agent_type=agent_type)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    f'Já existe uma versão {version} para o tipo "{agent_type}". '
                    f'Use uma versão diferente ou remova a existente.'
                )
        return cleaned