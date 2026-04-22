from django.urls import path
from .views import (
    RDPAgentSignalAnswerView,
    RDPAgentSignalPullView,
    RDPConfigView,
    RDPCloseView,
    RDPInfoView,
    RDPOfferView,
    RDPPolicyView,
    RDPSessionTokenView,
    RDPSessionsView,
)

app_name = 'rdp'

urlpatterns = [
    path('offer/', RDPOfferView.as_view(), name='rdp_offer'),
    path('close/', RDPCloseView.as_view(), name='rdp_close'),
    path('info/', RDPInfoView.as_view(), name='rdp_info'),
    path('sessions/', RDPSessionsView.as_view(), name='rdp_sessions'),
    path('policy/', RDPPolicyView.as_view(), name='rdp_policy'),
    path('config/', RDPConfigView.as_view(), name='rdp_config'),
    path('session-token/', RDPSessionTokenView.as_view(), name='rdp_session_token'),
    path('signal/pull/', RDPAgentSignalPullView.as_view(), name='rdp_signal_pull'),
    path('signal/answer/', RDPAgentSignalAnswerView.as_view(), name='rdp_signal_answer'),
]
