from datetime import datetime

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, DetailView, DeleteView, UpdateView
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.utils.decorators import method_decorator
from django.views import View
from .models import Movimentacao, Lote, HistoricoEstoque, TipoMovimentacao
from .forms import MovimentacaoForm, LoteForm, HistoricoEstoqueForm, TipoMovimentacaoForm
from ..produtos.models import Produto, VariacaoProduto
from ..fornecedor.models import Fornecedor
from django.shortcuts import render, redirect
from django.contrib import messages
import xml.etree.ElementTree as ET

from ..shared.mixins import ClienteQuerySetMixin, ClienteCreateMixin, ClienteObjectMixin
from django.contrib.auth import get_user_model

User = get_user_model()


class LoteListView(ClienteQuerySetMixin, LoginRequiredMixin, ListView):
    model = Lote
    template_name = 'movimentacao/lote_list.html'
    context_object_name = 'lotes'

    def get_queryset(self):
        queryset = super().get_queryset()
        numero_lote = self.request.GET.get('numero_lote')
        produto = self.request.GET.get('produto')
        fornecedor = self.request.GET.get('fornecedor')
        data_inicial = self.request.GET.get('data_inicial')
        data_final = self.request.GET.get('data_final')

        if numero_lote:
            queryset = queryset.filter(numero_lote__icontains=numero_lote)
        if produto:
            queryset = queryset.filter(variacao__produto__nome__icontains=produto)
        if fornecedor:
            queryset = queryset.filter(fornecedor__nome__icontains=fornecedor)
        if data_inicial:
            try:
                dt_ini = datetime.strptime(data_inicial, '%Y-%m-%d')
                queryset = queryset.filter(data_entrada__date__gte=dt_ini)
            except (ValueError, TypeError):
                pass
        if data_final:
            try:
                dt_fim = datetime.strptime(data_final, '%Y-%m-%d')
                queryset = queryset.filter(data_entrada__date__lte=dt_fim)
            except (ValueError, TypeError):
                pass
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['produtos'] = Produto.objects.all()
        context['fornecedores'] = Fornecedor.objects.all()
        return context


class LoteCreateView(ClienteCreateMixin, LoginRequiredMixin, CreateView):
    model = Lote
    template_name = 'movimentacao/lote_create.html'
    form_class = LoteForm
    success_url = reverse_lazy('movimentacao:lote_list')


class LoteDetailView(ClienteObjectMixin, LoginRequiredMixin, DetailView):
    model = Lote
    template_name = 'movimentacao/lote_detail.html'
    context_object_name = 'lote'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['movimentacoes'] = Movimentacao.objects.filter(lote=self.object).order_by('-created_at')
        return context


class LoteUpdateView(ClienteObjectMixin, LoginRequiredMixin, UpdateView):
    model = Lote
    template_name = 'movimentacao/lote_create.html'
    form_class = LoteForm
    success_url = reverse_lazy('movimentacao:lote_list')


class LoteDeleteView(ClienteObjectMixin, LoginRequiredMixin, DeleteView):
    model = Lote
    template_name = 'movimentacao/lote_delete.html'
    success_url = reverse_lazy('movimentacao:lote_list')


class MovimentacaoListView(ClienteQuerySetMixin, LoginRequiredMixin, ListView):
    model = Movimentacao
    template_name = 'movimentacao/movimentacao_list.html'
    context_object_name = 'movimentacao'
    paginate_by = 10

    def get_queryset(self):
        queryset = super().get_queryset()
        produto = self.request.GET.get('produto')
        tipo = self.request.GET.get('tipo')
        quantidade = self.request.GET.get('quantidade')
        data_inicial = self.request.GET.get('data_inicial')
        data_final = self.request.GET.get('data_final')

        if produto:
            queryset = queryset.filter(variacao__produto__nome__icontains=produto)
        if tipo:
            queryset = queryset.filter(
                tipo__nome__iexact=tipo)  # Use __iexact para ForeignKey, ou apenas tipo=tipo se for CharField
        if quantidade:
            try:
                quantidade = int(quantidade)
                queryset = queryset.filter(quantidade=quantidade)
            except (ValueError, TypeError):
                pass
        if data_inicial:
            try:
                dt_ini = datetime.strptime(data_inicial, '%Y-%m-%d')
                queryset = queryset.filter(data__gte=dt_ini)
            except (ValueError, TypeError):
                pass
        if data_final:
            try:
                dt_fim = datetime.strptime(data_final, '%Y-%m-%d')
                queryset = queryset.filter(data__lte=dt_fim)
            except (ValueError, TypeError):
                pass
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['tipos'] = [t.nome for t in TipoMovimentacao.objects.all()]
        context['produtos'] = Produto.objects.all()
        return context


class MovimentacaoCreateView(ClienteCreateMixin, LoginRequiredMixin, CreateView):
    model = Movimentacao
    template_name = 'movimentacao/movimentacao_create.html'
    form_class = MovimentacaoForm
    success_url = reverse_lazy('movimentacao:movimentacao_list')

    def form_valid(self, form):
        form.instance.usuario = self.request.user
        return super().form_valid(form)


class MovimentacaoDetailView(ClienteObjectMixin, LoginRequiredMixin, DetailView):
    model = Movimentacao
    template_name = 'movimentacao/detalhe_entrada.html'


class MovimentacaoDeleteView(ClienteObjectMixin, LoginRequiredMixin, DeleteView):
    model = Movimentacao
    template_name = 'movimentacao/movimentacao_delete.html'
    success_url = reverse_lazy('movimentacao:movimentacao_list')


class HistoricoEstoqueListView(ClienteQuerySetMixin, LoginRequiredMixin, ListView):
    model = HistoricoEstoque
    template_name = 'movimentacao/historico_estoque_list.html'
    context_object_name = 'historicos'
    paginate_by = 20

    def get_queryset(self):
        queryset = super().get_queryset()
        produto = self.request.GET.get('produto')
        tipo = self.request.GET.get('tipo_operacao')
        usuario = self.request.GET.get('usuario')
        data = self.request.GET.get('data')

        if produto:
            queryset = queryset.filter(variacao__produto__nome__icontains=produto)
        if tipo:
            queryset = queryset.filter(tipo_operacao=tipo)
        if usuario:
            queryset = queryset.filter(usuario__username__icontains=usuario)
        if data:
            try:
                data_obj = datetime.strptime(data, '%Y-%m-%d')
                queryset = queryset.filter(created_at__date=data_obj)
            except ValueError:
                pass
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['produtos'] = Produto.objects.all()
        context['tipos'] = HistoricoEstoque.TIPO_OPERACAO
        context['usuarios'] = User.objects.all()
        return context


class HistoricoEstoqueDetailView(ClienteObjectMixin, LoginRequiredMixin, DetailView):
    model = HistoricoEstoque
    template_name = 'movimentacao/historico_estoque_detail.html'
    context_object_name = 'historico'


class AjusteEstoqueCreateView(ClienteCreateMixin, LoginRequiredMixin, CreateView):
    model = Movimentacao
    template_name = 'movimentacao/ajuste_estoque_create.html'
    form_class = HistoricoEstoqueForm
    success_url = reverse_lazy('movimentacao:historico_estoque_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['initial']['request'] = self.request
        return kwargs


class BuscarProdutoPorCodigoView(LoginRequiredMixin, View):
    @method_decorator(require_GET)
    def get(self, request, *args, **kwargs):
        codigo = request.GET.get('codigo_barras', '')
        if not codigo:
            return JsonResponse({'error': 'Código de barras não fornecido'}, status=400)

        try:
            variacao = VariacaoProduto.objects.get(codigo_barras=codigo)
            return JsonResponse({
                'id': variacao.id,
                'nome': f"{variacao.produto.nome} - {variacao.tamanho}",
                'quantidade': variacao.quantidade,
            })
        except VariacaoProduto.DoesNotExist:
            return JsonResponse({'error': 'Variação de produto não encontrada'}, status=404)


class ValidarNumeroLoteView(LoginRequiredMixin, View):
    @method_decorator(require_GET)
    def get(self, request, *args, **kwargs):
        numero_lote = request.GET.get('numero_lote', '')
        exists = Lote.objects.filter(numero_lote=numero_lote).exists()
        return JsonResponse({'exists': exists})



class ImportarNFeView(LoginRequiredMixin, View):
    template_name = 'movimentacao/importar_nfe.html'

    def get(self, request):
        return render(request, self.template_name)

    def post(self, request):
        nfe_file = request.FILES['nfe_xml']
        tree = ET.parse(nfe_file)
        root = tree.getroot()
        ns = {'nfe': 'http://www.portalfiscal.inf.br/nfe'}

        erros = []
        produtos_importados = 0

        for det in root.findall('.//nfe:det', ns):
            try:
                codigo_barras = det.find('.//nfe:cProd', ns).text
                quantidade = float(det.find('.//nfe:qCom', ns).text.replace(',', '.'))
                preco_unitario = float(det.find('.//nfe:vUnCom', ns).text.replace(',', '.'))
                variacao = VariacaoProduto.objects.filter(codigo_barras=codigo_barras).first()
                if not variacao:
                    erros.append(f"Produto não cadastrado: {codigo_barras}")
                    continue

                numero_lote = f"{codigo_barras}-{root.find('.//nfe:ide/nfe:nNF', ns).text}"
                lote = Lote.objects.create(
                    variacao=variacao,
                    numero_lote=numero_lote,
                    quantidade=quantidade,
                    preco_unitario=preco_unitario,
                    documento_nfe=nfe_file
                )

                # Ajuste de estoque e custo
                variacao.quantidade += quantidade
                variacao.save()
                produto = variacao.produto
                produto.preco_custo = preco_unitario  # OU média, se preferir
                produto.save()

                produtos_importados += 1

            except Exception as e:
                erros.append(str(e))

        if produtos_importados > 0:
            messages.success(request, f'{produtos_importados} produtos/lotes importados com sucesso.')
        if erros:
            messages.error(request, f'Erros: {", ".join(erros)}')
        return redirect('movimentacao:lote_list')


class TipoMovimentacaoListView(ClienteQuerySetMixin, LoginRequiredMixin, ListView):
    model = TipoMovimentacao
    template_name = 'movimentacao/tipos_movimentacao_list.html'
    context_object_name = 'tipos'

class TipoMovimentacaoCreateView(ClienteCreateMixin, LoginRequiredMixin, CreateView):
    model = TipoMovimentacao
    form_class = TipoMovimentacaoForm
    template_name = 'movimentacao/tipo_movimentacao_edit.html'
    success_url = reverse_lazy('movimentacao:tipo_movimentacao_list')

class TipoMovimentacaoUpdateView(ClienteObjectMixin, LoginRequiredMixin, UpdateView):
    model = TipoMovimentacao
    form_class = TipoMovimentacaoForm
    template_name = 'movimentacao/tipo_movimentacao_edit.html'
    success_url = reverse_lazy('movimentacao:tipo_movimentacao_list')