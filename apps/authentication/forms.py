from django import forms
from .models import User


class ClienteUserForm(forms.ModelForm):

    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'first_name', 'last_name', 'is_staff']

        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'password': forms.PasswordInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'exemplo@dominio.com'}),
            'is_staff': forms.CheckboxInput(attrs={'class': 'form-check-input'})
        }
        labels = {
            'username': 'Usuário',
            'first_name': 'Nome',
            'last_name': 'Sobrenome',
            'email': 'E-mail',
            'is_staff': 'Administrador?',
            'password': 'Senha',
        }

    # Opcional: esconder campo senha ao editar usuário
    # def __init__(self, *args, **kwargs):
    #         super().__init__(*args, **kwargs)
    #         if self.instance and self.instance.pk:
    #             self.fields['password'].required = False
    #             self.fields['password'].widget = forms.HiddenInput()

    def save(self, commit=True, cliente=None):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        if cliente:
            user.cliente = cliente
        if commit:
            user.save()
        return user