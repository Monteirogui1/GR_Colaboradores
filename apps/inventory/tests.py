
import json
import hashlib
from datetime import timedelta

from django.test import TestCase, Client
from django.utils import timezone
from django.urls import reverse
from django.contrib.auth import get_user_model

from .models import (
    Machine, MachineGroup, AgentToken, AgentTokenUsage,
    AgentVersion, Notification, BlockedSite,
)

User = get_user_model()


# ============================================================================
# FIXTURES / HELPERS
# ============================================================================

def make_token(user, active=True, days=1):
    """Cria e retorna um AgentToken válido."""
    raw = AgentToken.generate_token()
    token = AgentToken.objects.create(
        token=raw,
        token_hash=AgentToken.hash_token(raw),
        created_by=user,
        is_active=active,
        expires_at=timezone.now() + timedelta(days=days),
    )
    return raw, token


def make_machine(hostname="PC-TEST", ip="192.168.1.1", online=True):
    machine = Machine.objects.create(
        hostname=hostname,
        ip_address=ip,
        is_online=online,
        last_seen=timezone.now() if online else None,
    )
    return machine


# ============================================================================
# MODEL: AgentToken
# ============================================================================

class AgentTokenGenerateTest(TestCase):
    def test_token_length(self):
        token = AgentToken.generate_token()
        self.assertEqual(len(token), 8)

    def test_token_has_uppercase(self):
        token = AgentToken.generate_token()
        self.assertTrue(any(c.isupper() for c in token))

    def test_token_has_lowercase(self):
        token = AgentToken.generate_token()
        self.assertTrue(any(c.islower() for c in token))

    def test_token_has_digit(self):
        token = AgentToken.generate_token()
        self.assertTrue(any(c.isdigit() for c in token))

    def test_token_has_special(self):
        token = AgentToken.generate_token()
        self.assertTrue(any(c in "!@#$%&*" for c in token))

    def test_hash_token(self):
        raw = "Ab1!Cd2@"
        expected = hashlib.sha256(raw.encode()).hexdigest()
        self.assertEqual(AgentToken.hash_token(raw), expected)

    def test_tokens_are_unique(self):
        tokens = {AgentToken.generate_token() for _ in range(50)}
        self.assertEqual(len(tokens), 50)


class AgentTokenExpiryTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="admin", password="pass")

    def test_not_expired_when_future(self):
        _, token = make_token(self.user, days=1)
        self.assertFalse(token.is_expired())

    def test_expired_when_past(self):
        raw = AgentToken.generate_token()
        token = AgentToken.objects.create(
            token=raw,
            token_hash=AgentToken.hash_token(raw),
            created_by=self.user,
            is_active=True,
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        self.assertTrue(token.is_expired())


class AgentTokenStatusDisplayTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="admin", password="pass")

    def test_inactive_status(self):
        _, token = make_token(self.user, active=False)
        self.assertEqual(token.get_status_display()['text'], 'Inativo')
        self.assertEqual(token.get_status_display()['class'], 'secondary')

    def test_expired_status(self):
        raw = AgentToken.generate_token()
        token = AgentToken.objects.create(
            token=raw,
            token_hash=AgentToken.hash_token(raw),
            created_by=self.user,
            is_active=True,
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        self.assertEqual(token.get_status_display()['text'], 'Expirado')

    def test_available_status(self):
        _, token = make_token(self.user)
        self.assertEqual(token.get_status_display()['text'], 'Disponível')
        self.assertEqual(token.get_status_display()['class'], 'success')

    def test_in_use_status(self):
        _, token = make_token(self.user)
        AgentTokenUsage.objects.create(
            agent_token=token,
            machine_name="PC-001",
        )
        display = token.get_status_display()
        self.assertIn('Em uso', display['text'])
        self.assertEqual(display['class'], 'info')


# ============================================================================
# MODEL: Machine
# ============================================================================

class MachineOnlineStatusTest(TestCase):
    def test_online_when_recent_last_seen(self):
        machine = make_machine()
        machine.last_seen = timezone.now() - timedelta(minutes=5)
        machine.save()
        self.assertTrue(machine.is_currently_online)

    def test_offline_when_no_last_seen(self):
        machine = Machine.objects.create(hostname="NOTIME", ip_address="10.0.0.1")
        self.assertFalse(machine.is_currently_online)

    def test_offline_when_old_last_seen(self):
        machine = make_machine()
        machine.last_seen = timezone.now() - timedelta(hours=2)
        machine.save()
        self.assertFalse(machine.is_currently_online)

    def test_update_online_status_saves(self):
        machine = make_machine()
        machine.is_online = True
        machine.last_seen = timezone.now() - timedelta(hours=2)
        machine.save()
        machine.update_online_status()
        machine.refresh_from_db()
        self.assertFalse(machine.is_online)


# ============================================================================
# MODEL: Notification
# ============================================================================

class NotificationTest(TestCase):
    def setUp(self):
        self.machine = make_machine()

    def _make_notification(self, **kwargs):
        defaults = dict(machine=self.machine, title="Teste", message="msg")
        defaults.update(kwargs)
        return Notification.objects.create(**defaults)

    def test_mark_as_read(self):
        n = self._make_notification()
        n.mark_as_read()
        self.assertTrue(n.is_read)
        self.assertEqual(n.status, 'read')
        self.assertIsNotNone(n.read_at)

    def test_not_expired_without_expires_at(self):
        n = self._make_notification()
        self.assertFalse(n.is_expired())

    def test_expired_when_past_expires_at(self):
        n = self._make_notification(expires_at=timezone.now() - timedelta(hours=1))
        self.assertTrue(n.is_expired())

    def test_not_expired_when_future_expires_at(self):
        n = self._make_notification(expires_at=timezone.now() + timedelta(hours=1))
        self.assertFalse(n.is_expired())

    def test_is_urgent_high_priority(self):
        n = self._make_notification(priority='high')
        self.assertTrue(n.is_urgent)

    def test_is_urgent_critical_priority(self):
        n = self._make_notification(priority='critical')
        self.assertTrue(n.is_urgent)

    def test_not_urgent_normal_priority(self):
        n = self._make_notification(priority='normal')
        self.assertFalse(n.is_urgent)

    def test_save_sets_expired_status_automatically(self):
        n = self._make_notification(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(n.status, 'expired')

    def test_save_sets_read_at_when_is_read(self):
        n = self._make_notification()
        n.is_read = True
        n.save()
        self.assertIsNotNone(n.read_at)
        self.assertEqual(n.status, 'read')

    def test_age_in_hours_is_non_negative(self):
        n = self._make_notification()
        self.assertGreaterEqual(n.age_in_hours, 0)


# ============================================================================
# MODEL: AgentVersion
# ============================================================================

class AgentVersionTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="admin", password="pass")

    def test_version_tuple(self):
        self.assertEqual(AgentVersion.version_tuple("1.2.3"), (1, 2, 3))
        self.assertEqual(AgentVersion.version_tuple("10.0.0"), (10, 0, 0))
        self.assertEqual(AgentVersion.version_tuple("bad"), (0, 0, 0))

    def test_latest_active_returns_none_when_empty(self):
        result = AgentVersion.latest_active("service")
        self.assertIsNone(result)

    def test_latest_active_returns_highest_semantic_version(self):
        for v in ["1.0.0", "2.0.0", "1.9.0"]:
            AgentVersion.objects.create(
                version=v,
                agent_type="service",
                file_path="agent_versions/dummy.exe",
                release_notes="notes",
                is_active=True,
                created_by=self.user,
            )
        latest = AgentVersion.latest_active("service")
        self.assertEqual(latest.version, "2.0.0")

    def test_latest_active_ignores_inactive(self):
        AgentVersion.objects.create(
            version="3.0.0",
            agent_type="service",
            file_path="agent_versions/dummy.exe",
            release_notes="notes",
            is_active=False,
            created_by=self.user,
        )
        result = AgentVersion.latest_active("service")
        self.assertIsNone(result)


# ============================================================================
# VIEW: MachineCheckinView
# ============================================================================

class MachineCheckinViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="admin", password="pass")
        self.raw_token, self.token = make_token(self.user)
        self.url = reverse('inventario:checkin')

    def _post(self, payload):
        return self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type='application/json',
        )

    def test_checkin_creates_machine(self):
        payload = {
            "hostname": "PC-NEW",
            "ip": "192.168.1.50",
            "token": self.token.token_hash,
            "hardware": {"ram_gb": 16},
        }
        resp = self._post(payload)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Machine.objects.filter(hostname="PC-NEW").exists())

    def test_checkin_updates_existing_machine(self):
        make_machine(hostname="PC-EXIST", ip="10.0.0.1")
        payload = {
            "hostname": "PC-EXIST",
            "ip": "10.0.0.99",
            "token": self.token.token_hash,
            "hardware": {},
        }
        resp = self._post(payload)
        self.assertEqual(resp.status_code, 200)
        machine = Machine.objects.get(hostname="PC-EXIST")
        self.assertEqual(machine.ip_address, "10.0.0.99")

    def test_checkin_invalid_token_returns_401(self):
        payload = {
            "hostname": "PC-X",
            "ip": "1.2.3.4",
            "token": "invalid-hash",
            "hardware": {},
        }
        resp = self._post(payload)
        self.assertEqual(resp.status_code, 401)

    def test_checkin_expired_token_returns_401(self):
        raw = AgentToken.generate_token()
        expired = AgentToken.objects.create(
            token=raw,
            token_hash=AgentToken.hash_token(raw),
            created_by=self.user,
            is_active=True,
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        payload = {
            "hostname": "PC-X",
            "ip": "1.2.3.4",
            "token": expired.token_hash,
            "hardware": {},
        }
        resp = self._post(payload)
        self.assertEqual(resp.status_code, 401)

    def test_checkin_registers_token_usage(self):
        payload = {
            "hostname": "PC-USAGE",
            "ip": "10.10.10.1",
            "token": self.token.token_hash,
            "hardware": {},
        }
        self._post(payload)
        self.assertTrue(
            AgentTokenUsage.objects.filter(
                agent_token=self.token, machine_name="PC-USAGE"
            ).exists()
        )


# ============================================================================
# VIEW: AgentHealthCheckAPIView
# ============================================================================

class AgentHealthCheckTest(TestCase):
    def test_health_returns_200(self):
        resp = self.client.get(reverse('inventario:api_health_check'))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get('status'), 'ok')