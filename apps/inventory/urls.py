from django.urls import path
from .views import (
    # API Endpoints
    MachineCheckinView,
    RunCommandView,
    AgentDownloadView,
    MachineNotificationView,
    AgentVersionView,

    # Machine Views
    MachineListView,
    MachineDetailView,
    MachineCreateView,
    MachineUpdateView,
    MachineDeleteView,

    # Machine Group Views
    MachineGroupListView,
    MachineGroupCreateView,
    MachineGroupUpdateView,
    MachineGroupDeleteView,

    # Blocked Site Views
    BlockedSiteListView,
    BlockedSiteCreateView,
    BlockedSiteUpdateView,
    BlockedSiteDeleteView,

    # Notification Views
    NotificationListView,
    NotificationDetailView,
    NotificationCreateView,
    NotificationDeleteView, AgentVersionListView, AgentVersionCreateView, AgentTokenDeleteView, AgentVersionToggleView,
    AgentValidateTokenAPIView, AgentCheckUpdateAPIView, AgentDownloadAPIView, AgentHealthCheckAPIView,
    AgentTokenDeactivateView, AgentTokenCreateView, AgentTokenListView,
)

app_name = 'inventario'

urlpatterns = [
    # ==================== API ENDPOINTS ====================
    path('checkin/', MachineCheckinView.as_view(), name='checkin'),
    path('run/<int:machine_id>/', RunCommandView.as_view(), name='run_command'),
    path('notifications/', MachineNotificationView.as_view(), name='machine-notifications'),
    path('agent/download/', AgentDownloadView.as_view(), name='agent_download'),
    path('agent/version/', AgentVersionView.as_view(), name='agent_version'),

    # ==================== MACHINES ====================
    path('machines/', MachineListView.as_view(), name='machine_list'),
    path('machines/<int:pk>/', MachineDetailView.as_view(), name='machine_detail'),
    path('machines/new/', MachineCreateView.as_view(), name='machine_create'),
    path('machines/<int:pk>/edit/', MachineUpdateView.as_view(), name='machine_update'),
    path('machines/<int:pk>/delete/', MachineDeleteView.as_view(), name='machine_delete'),

    # ==================== GROUPS ====================
    path('groups/', MachineGroupListView.as_view(), name='group_list'),
    path('groups/new/', MachineGroupCreateView.as_view(), name='group_create'),
    path('groups/<int:pk>/edit/', MachineGroupUpdateView.as_view(), name='group_update'),
    path('groups/<int:pk>/delete/', MachineGroupDeleteView.as_view(), name='group_delete'),

    # ==================== BLOCKED SITES ====================
    path('blocked-sites/', BlockedSiteListView.as_view(), name='blockedsite_list'),
    path('blocked-sites/new/', BlockedSiteCreateView.as_view(), name='blockedsite_create'),
    path('blocked-sites/<int:pk>/edit/', BlockedSiteUpdateView.as_view(), name='blockedsite_update'),
    path('blocked-sites/<int:pk>/delete/', BlockedSiteDeleteView.as_view(), name='blockedsite_delete'),

    # ==================== NOTIFICATIONS ====================
    path('notifications/', NotificationListView.as_view(), name='notification_list'),
    path('notifications/<int:pk>/', NotificationDetailView.as_view(), name='notification_detail'),
    path('notifications/new/', NotificationCreateView.as_view(), name='notification_create'),
    path('notifications/<int:pk>/delete/', NotificationDeleteView.as_view(), name='notification_delete'),

    # ============================================================================
    # GERENCIAMENTO DE TOKENS (Requer Login)
    # ============================================================================

    path(
        'agent/tokens/',
        AgentTokenListView.as_view(),
        name='token_list'
    ),

    path(
        'agent/tokens/create/',
        AgentTokenCreateView.as_view(),
        name='token_create'
    ),

    path(
        'agent/tokens/<int:pk>/deactivate/',
        AgentTokenDeactivateView.as_view(),
        name='token_deactivate'
    ),

    path(
        'agent/tokens/<int:pk>/delete/',
        AgentTokenDeleteView.as_view(),
        name='token_delete'
    ),

    # ============================================================================
    # GERENCIAMENTO DE VERSÕES (Requer Login)
    # ============================================================================

    path(
        'agent/versions/',
        AgentVersionListView.as_view(),
        name='version_list'
    ),

    path(
        'agent/versions/create/',
        AgentVersionCreateView.as_view(),
        name='version_create'
    ),

    path(
        'agent/versions/<int:pk>/toggle/',
        AgentVersionToggleView.as_view(),
        name='version_toggle'
    ),

    # ============================================================================
    # API ENDPOINTS (Sem autenticação - para o agente usar)
    # ============================================================================

    path(
        'inventario/agent/validate/',
        AgentValidateTokenAPIView.as_view(),
        name='api_validate_token'
    ),

    path(
        'inventario/agent/update/',
        AgentCheckUpdateAPIView.as_view(),
        name='api_check_update'
    ),

    path(
        'inventario/agent/download/<int:pk>/',
        AgentDownloadAPIView.as_view(),
        name='api_download_agent'
    ),

    path(
        'inventario/health/',
        AgentHealthCheckAPIView.as_view(),
        name='api_health_check'
    ),
]
