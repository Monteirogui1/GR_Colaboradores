from django.urls import path
from .views import (
    MachineCheckinView,
    RunCommandView,
    AgentDownloadView, MachineNotificationView, AgentVersionView
)

urlpatterns = [
    path('checkin/', MachineCheckinView.as_view(), name='checkin'),
    path('run/<int:machine_id>/', RunCommandView.as_view(), name='run_command'),

    path('api/notifications/', MachineNotificationView.as_view(), name='machine-notifications'),
    path('agent/download/', AgentDownloadView.as_view(), name='agent_download'),
    path('agent/version/', AgentVersionView.as_view(), name='agent_version'),
]