from django.conf import settings
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.urls import path, include
from django.views.generic import TemplateView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('dashboard/', include('apps.home.urls')),
    path('', include('apps.authentication.urls', namespace='login')),
    path('', include('apps.categorias.urls',)),
    path('', include('apps.fornecedor.urls',)),
    path('', include('apps.marcas.urls',)),
    path('', include('apps.ativos.urls')),
    path('', include('apps.auditoria.urls')),
    path('', include('apps.tickets.urls')),
    path('', include('apps.produtos.urls',)),
    path('', include('apps.movimentacao.urls',)),
    path('api/', include('apps.inventory.urls')),
    path('', include('apps.notificacao.urls', )),

    path(
        'rdp/',
        login_required(TemplateView.as_view(template_name='rdp/remote_desktop.html')),
        name='remote_desktop',
    ),
    # API de sinalização WebRTC
    path('api/rdp/', include('apps.rdp.urls')),

    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/schema/swagger-ui/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/schema/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),

]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)