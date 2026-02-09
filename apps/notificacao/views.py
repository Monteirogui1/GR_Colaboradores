from django.shortcuts import render
from django.views.generic import TemplateView, RedirectView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404
from django.urls import reverse_lazy
from .models import Notificacao
from ..shared.mixins import ClienteObjectMixin


# class BaseView(TemplateView):
#     template_name = 'layouts/base.html'
#
#     def get_context_data(self, **kwargs):
#         context = super().get_context_data(**kwargs)
#         context['notificacoes'] = Notificacao.objects.filter(lida=False)
#         print(context)
#         return context
#

class MarcarNotificacaoLidaView(ClienteObjectMixin, LoginRequiredMixin, RedirectView):

    def get(self, request, *args, **kwargs):
        notificacao_id = self.kwargs.get('notificacao_id')

        notificacao = get_object_or_404(Notificacao, id=notificacao_id)

        notificacao.lida = True
        notificacao.save()

        return super().get(request, *args, **kwargs)

    def get_redirect_url(self, *args, **kwargs):
        return self.request.META.get('HTTP_REFERER', super().get_redirect_url(*args, **kwargs))