from rest_framework import serializers
from .models import AgentVersion, AgentDownloadLog


class AgentVersionSerializer(serializers.ModelSerializer):
    """
    Serializer de leitura pública para AgentVersion.

    Exposto nos endpoints de check/download — nunca inclui file_path
    diretamente para forçar o uso do endpoint autenticado de download.
    """

    agent_type_display = serializers.CharField(
        source="get_agent_type_display", read_only=True
    )

    class Meta:
        model = AgentVersion
        fields = [
            "id",
            "version",
            "agent_type",
            "agent_type_display",
            "sha256",
            "release_notes",
            "is_mandatory",
            "created_at",
        ]
        read_only_fields = fields


class AgentDownloadLogSerializer(serializers.ModelSerializer):
    """
    Serializer de leitura para logs de download.

    Usado no endpoint administrativo de auditoria.
    """

    version = serializers.CharField(source="agent_version.version", read_only=True)
    agent_type = serializers.CharField(source="agent_version.agent_type", read_only=True)

    class Meta:
        model = AgentDownloadLog
        fields = ["id", "version", "agent_type", "machine_name", "ip_address", "downloaded_at"]
        read_only_fields = fields