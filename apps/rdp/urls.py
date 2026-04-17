from django.urls import path
from .views import RDPOfferView, RDPInfoView, RDPSessionsView, RDPConfigView, RDPMachineTokenView

app_name = 'rdp'

urlpatterns = [
    path('offer/', RDPOfferView.as_view(), name='rdp_offer'),
    path('info/', RDPInfoView.as_view(), name='rdp_info'),
    path('sessions/', RDPSessionsView.as_view(), name='rdp_sessions'),
    path('config/', RDPConfigView.as_view(), name='rdp_config'),
    path('machine-token/', RDPMachineTokenView.as_view(), name='rdp_machine_token'),
]