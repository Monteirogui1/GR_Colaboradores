from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.inventory.models import AgentToken, AgentTokenUsage, Machine
from apps.rdp.models import RDPSessionToken


class RDPSessionTokenTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="tech",
            password="secret123",
            is_staff=True,
        )
        self.machine = Machine.objects.create(hostname="PC-001", ip_address="10.0.0.10")
        self.agent_token = AgentToken.objects.create(
            token="Ab1$Cd2@",
            token_hash=AgentToken.hash_token("Ab1$Cd2@"),
            created_by=self.user,
            expires_at=timezone.now() + timedelta(days=1),
            is_active=True,
        )
        AgentTokenUsage.objects.create(agent_token=self.agent_token, machine_name=self.machine.hostname)
        self.client.force_login(self.user)

    def test_issue_session_token(self):
        url = reverse("rdp:rdp_session_token")
        resp = self.client.post(
            url,
            data={"machine": self.machine.hostname, "reason": "Atendimento remoto"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("token", data)
        self.assertGreaterEqual(len(data["token"]), 16)
        self.assertTrue(
            RDPSessionToken.objects.filter(
                machine=self.machine,
                created_by=self.user,
                token_hash=AgentToken.hash_token(data["token"]),
            ).exists()
        )

    def test_policy_endpoint_returns_defaults(self):
        url = reverse("rdp:rdp_policy")
        resp = self.client.get(f"{url}?machine={self.machine.hostname}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["connection_mode"], "auto")
        self.assertTrue(data["silent_access_only"])

    def test_config_p2p_only_returns_stun_only(self):
        url = reverse("rdp:rdp_config")
        resp = self.client.get(f"{url}?machine={self.machine.hostname}&mode=p2p_only")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["mode"], "p2p_only")
        self.assertGreaterEqual(len(data["ice_servers"]), 1)
        urls = str(data["ice_servers"][0].get("urls", ""))
        self.assertIn("stun:", urls)

    def test_rdp_info_rejects_invalid_token(self):
        url = reverse("rdp:rdp_info")
        resp = self.client.get(
            f"{url}?machine={self.machine.hostname}",
            HTTP_X_RDP_TOKEN="invalid-token-value",
        )
        self.assertEqual(resp.status_code, 403)
