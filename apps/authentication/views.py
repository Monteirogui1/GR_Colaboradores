from django.urls import reverse_lazy
from django.views.generic import TemplateView
from django.contrib.auth.views import LoginView

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from .models import User
from .forms import ClienteUserForm


# PÁGINA LOGIN
# ----------------------------------------------

class ErpLoginView(LoginView):
    template_name = 'registration/login.html'
    success_url = reverse_lazy('home:dashboard')
    redirect_authenticated_user = True



class ClienteUserListView(LoginRequiredMixin, ListView):
    model = User
    template_name = 'authentication/clienteuser_list.html'

    def get_queryset(self):
        # Começa filtrando só usuários do cliente do usuário logado
        queryset = User.objects.filter(cliente=self.request.user.cliente)

        nome = self.request.GET.get('nome')
        email = self.request.GET.get('email')
        admin = self.request.GET.get('is_staff')

        if nome:
            queryset = queryset.filter(username__icontains=nome)
        if email:
            queryset = queryset.filter(email__icontains=email)
        if admin in ["true", "false"]:
            queryset = queryset.filter(is_staff=(admin == "true"))

        return queryset

class ClienteUserCreateView(LoginRequiredMixin, CreateView):
    model = User
    form_class = ClienteUserForm
    template_name = 'authentication/clienteuser_form.html'
    success_url = reverse_lazy('authentication:clienteuser_list')

    def form_valid(self, form):
        form.save(cliente=self.request.user.cliente)
        return super().form_valid(form)

class ClienteUserUpdateView(LoginRequiredMixin, UpdateView):
    model = User
    form_class = ClienteUserForm
    template_name = 'authentication/clienteuser_form.html'
    success_url = reverse_lazy('authentication:clienteuser_list')

    def get_queryset(self):
        return User.objects.filter(cliente=self.request.user.cliente)

class ClienteUserDeleteView(LoginRequiredMixin, DeleteView):
    model = User
    template_name = 'authentication/clienteuser_confirm_delete.html'
    success_url = reverse_lazy('authentication:clienteuser_list')

    def get_queryset(self):
        return User.objects.filter(cliente=self.request.user.cliente)