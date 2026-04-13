from django.shortcuts import get_object_or_404
from apps.authentication.models import Cliente

# ListView: filtra queryset pelo cliente do usuário logado
class ClienteQuerySetMixin:
    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        cliente = getattr(user, 'cliente', None)
        if cliente is None:
            return qs.none()
        if not isinstance(cliente, Cliente):
            return qs.none()
        return qs.filter(cliente=cliente)

# DetailView, UpdateView, DeleteView: busca objeto só do cliente
class ClienteObjectMixin:
    def get_object(self):
        user = self.request.user
        return get_object_or_404(self.model, pk=self.kwargs['pk'], cliente=user.cliente)

# CreateView: atribui o cliente automaticamente antes de salvar
class ClienteCreateMixin:
    def form_valid(self, form):
        form.instance.cliente = self.request.user.cliente
        return super().form_valid(form)

# Admin: mostra apenas objetos do cliente do usuário logado
class ClienteAdminMixin:
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(cliente=request.user.cliente)
