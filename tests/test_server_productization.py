import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class ServerProductizationTests(unittest.TestCase):
    def setUp(self):
        self._env = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)

    def test_production_rejects_free_mode_without_secrets(self):
        from server.settings import ServerSettings

        os.environ["REACHLY_ENVIRONMENT"] = "production"
        os.environ["REACHLY_FREE_MODE"] = "true"
        os.environ.pop("REACHLY_SESSION_SECRET", None)
        os.environ.pop("REACHLY_VAULT_KEY", None)

        with self.assertRaises(RuntimeError):
            ServerSettings()

    def test_sqlite_migration_adds_strategy_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "reachly.db"
            env = os.environ.copy()
            env["REACHLY_DATABASE_URL"] = f"sqlite:///{db_path}"
            proc = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "from server.db import init_db, engine; "
                        "init_db(); "
                        "cols={r[1] for r in engine.connect().exec_driver_sql("
                        "'PRAGMA table_info(businessprofilerow)').fetchall()}; "
                        "assert {'goals','context_repo','posting_style'} <= cols"
                    ),
                ],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_sqlite_migration_adds_hygaar_identity_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "reachly.db"
            env = os.environ.copy()
            env["REACHLY_DATABASE_URL"] = f"sqlite:///{db_path}"
            proc = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "from server.db import init_db, engine; "
                        "init_db(); "
                        "cols={r[1] for r in engine.connect().exec_driver_sql("
                        "'PRAGMA table_info(user)').fetchall()}; "
                        "assert {'auth_provider','hygaar_user_id','email','username','roles',"
                        "'post_times','instagram_offset_minutes','medium_times'} <= cols"
                    ),
                ],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_internal_knowledge_event_endpoint_records_global_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "reachly.db"
            media_dir = tmp_path / "media"
            env = os.environ.copy()
            env["REACHLY_DATABASE_URL"] = f"sqlite:///{db_path}"
            env["REACHLY_SESSION_SECRET"] = "test-session-secret"
            env["REACHLY_VAULT_KEY"] = "AbCdEfGhIjKlMnOpQrStUvWxYz01234567890123456="
            env["REACHLY_MEDIA_DIR"] = str(media_dir)
            env["REACHLY_KNOWLEDGE_EVENT_SECRET"] = "knowledge-secret"
            proc = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "from pathlib import Path\n"
                        "from fastapi.testclient import TestClient\n"
                        "from server.app import app\n"
                        "from server.db import init_db\n"
                        "init_db()\n"
                        "client=TestClient(app)\n"
                        "payload={"
                        "'title':'Prod release',"
                        "'summary':'Added long-form narration-led videos for LinkedIn and YouTube.',"
                        "'source':'github_actions',"
                        "'environment':'prod',"
                        "'commit_sha':'abc123',"
                        "'files':['reachly/longform_video.py']"
                        "}\n"
                        "bad=client.post('/internal/knowledge-events', json=payload)\n"
                        "assert bad.status_code == 401, bad.text\n"
                        "ok=client.post('/internal/knowledge-events', json=payload, "
                        "headers={'x-reachly-knowledge-secret':'knowledge-secret'})\n"
                        "assert ok.status_code == 200, ok.text\n"
                        f"path=Path({str(tmp_path / 'knowledge' / 'knowledge_bank.md')!r})\n"
                        "text=path.read_text(encoding='utf-8')\n"
                        "assert 'Prod release' in text\n"
                        "assert 'long-form narration-led videos' in text\n"
                        "assert 'reachly/longform_video.py' in text\n"
                    ),
                ],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_hygaar_login_bridge_returns_tokens_and_user(self):
        from server.hygaar_auth import login_with_hygaar

        class Response:
            status_code = 200

            def json(self):
                return {
                    "status": "success",
                    "data": {
                        "access_token": "access",
                        "refresh_token": "refresh",
                        "user": {
                            "user_id": "ADM-123",
                            "email": "rohitsharma@hygaar.com",
                            "username": "Rohit",
                            "roles": ["Administrator"],
                        },
                    },
                }

        with patch("server.hygaar_auth.requests.post", return_value=Response()) as post:
            result = login_with_hygaar("RohitSharma@Hygaar.com", "secret")

        self.assertEqual(result.access_token, "access")
        self.assertEqual(result.user["user_id"], "ADM-123")
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["email"], "rohitsharma@hygaar.com")
        self.assertEqual(payload["password"], "secret")

    def test_hygaar_login_bridge_surfaces_auth_failure(self):
        from server.hygaar_auth import HygaarAuthError, login_with_hygaar

        class Response:
            status_code = 401

            def json(self):
                return {"status": "error", "message": "Invalid credentials"}

        with patch("server.hygaar_auth.requests.post", return_value=Response()):
            with self.assertRaises(HygaarAuthError) as ctx:
                login_with_hygaar("rohitsharma@hygaar.com", "bad")

        self.assertIn("Invalid credentials", str(ctx.exception))

    def test_preflight_rejects_invalid_production_public_url(self):
        from server.preflight import validate_settings
        from server.settings import ServerSettings

        os.environ["REACHLY_ENVIRONMENT"] = "production"
        os.environ["REACHLY_FREE_MODE"] = "false"
        os.environ["REACHLY_SESSION_SECRET"] = "test-session-secret"
        os.environ["REACHLY_VAULT_KEY"] = "AbCdEfGhIjKlMnOpQrStUvWxYz01234567890123456="
        os.environ["REACHLY_PUBLIC_BASE_URL"] = "http://reachly.hygaar.com"

        errors, warnings = validate_settings(ServerSettings())

        self.assertIn("REACHLY_PUBLIC_BASE_URL must be https:// in production.", errors)
        self.assertTrue(any("SQLite" in warning for warning in warnings))

    def test_preflight_hygaar_auth_does_not_print_tokens(self):
        from server.hygaar_auth import HygaarLoginResult
        from server.preflight import run_hygaar_auth_check

        env = {
            "REACHLY_PREFLIGHT_HYGAAR_EMAIL": "rohitsharma@hygaar.com",
            "REACHLY_PREFLIGHT_HYGAAR_PASSWORD": "secret",
        }
        result = HygaarLoginResult(
            access_token="access-token-secret",
            refresh_token="refresh-token-secret",
            user={
                "user_id": "ADM-123",
                "email": "rohitsharma@hygaar.com",
                "username": "Rohit",
                "roles": ["Admin"],
            },
        )

        with patch("server.preflight.login_with_hygaar", return_value=result):
            ok, message = run_hygaar_auth_check(env)

        self.assertTrue(ok)
        self.assertIn("rohitsharma@hygaar.com", message)
        self.assertIn("ADM-123", message)
        self.assertNotIn("access-token-secret", message)
        self.assertNotIn("refresh-token-secret", message)
        self.assertNotIn("secret", message)

    def test_hygaar_login_route_creates_reachly_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "reachly.db"
            env = os.environ.copy()
            env["REACHLY_DATABASE_URL"] = f"sqlite:///{db_path}"
            env["REACHLY_SESSION_SECRET"] = "test-session-secret"
            env["REACHLY_VAULT_KEY"] = "AbCdEfGhIjKlMnOpQrStUvWxYz01234567890123456="
            env["REACHLY_FREE_MODE"] = "false"
            env["REACHLY_HYGAAR_PRO_EMAILS"] = "rohitsharma@hygaar.com"
            proc = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "from unittest.mock import patch\n"
                        "from fastapi.testclient import TestClient\n"
                        "from server.hygaar_auth import HygaarLoginResult\n"
                        "from server.app import app\n"
                        "from server.db import init_db, get_session, User\n"
                        "init_db()\n"
                        "result=HygaarLoginResult(\n"
                        "    access_token='access', refresh_token='refresh',\n"
                        "    user={'user_id':'ADM-123','email':'rohitsharma@hygaar.com',"
                        "'username':'Rohit','roles':['Admin']},\n"
                        ")\n"
                        "with patch('server.app.login_with_hygaar', return_value=result):\n"
                        "    client=TestClient(app)\n"
                        "    res=client.post('/auth/hygaar/login', data={"
                        "'email':'rohitsharma@hygaar.com','password':'secret'}, "
                        "follow_redirects=False)\n"
                        "    assert res.status_code == 303, res.text\n"
                        "    assert res.headers['location'] == '/dashboard'\n"
                        "    dash=client.get('/dashboard')\n"
                        "    assert dash.status_code == 200, dash.text[:200]\n"
                        "    assert 'Reachly dashboard' in dash.text\n"
                        "with get_session() as s:\n"
                        "    user=s.query(User).filter(User.hygaar_user_id=='ADM-123').first()\n"
                        "    assert user.email == 'rohitsharma@hygaar.com'\n"
                        "    assert user.is_active and user.plan == 'pro'\n"
                    ),
                ],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_profile_and_billing_pages_require_session_and_render_for_hygaar_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "reachly.db"
            env = os.environ.copy()
            env["REACHLY_DATABASE_URL"] = f"sqlite:///{db_path}"
            env["REACHLY_SESSION_SECRET"] = "test-session-secret"
            env["REACHLY_VAULT_KEY"] = "AbCdEfGhIjKlMnOpQrStUvWxYz01234567890123456="
            proc = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "from fastapi.testclient import TestClient\n"
                        "from unittest.mock import patch\n"
                        "from server.hygaar_auth import HygaarLoginResult\n"
                        "from server.app import app\n"
                        "from server.db import init_db, get_session, User, BusinessProfileRow\n"
                        "init_db()\n"
                        "with get_session() as s:\n"
                        "    user=User(auth_provider='hygaar', hygaar_user_id='ADM-123', "
                        "email='rohitsharma@hygaar.com', username='Rohit', "
                        "is_active=True, plan='pro')\n"
                        "    s.add(user); s.commit(); s.refresh(user)\n"
                        "    s.add(BusinessProfileRow(user_id=user.id, name='Hygaar'))\n"
                        "    s.commit()\n"
                        "client=TestClient(app)\n"
                        "for path in ('/profile','/billing'):\n"
                        "    res=client.get(path, follow_redirects=False)\n"
                        "    assert res.status_code == 303, (path, res.status_code)\n"
                        "result=HygaarLoginResult(\n"
                        "    access_token='access', refresh_token='refresh',\n"
                        "    user={'user_id':'ADM-123','email':'rohitsharma@hygaar.com',"
                        "'username':'Rohit','roles':['Admin']},\n"
                        ")\n"
                        "with patch('server.app.login_with_hygaar', return_value=result):\n"
                        "    login=client.post('/auth/hygaar/login', data={"
                        "'email':'rohitsharma@hygaar.com','password':'secret'}, "
                        "follow_redirects=False)\n"
                        "    assert login.status_code == 303, login.text\n"
                        "profile=client.get('/profile')\n"
                        "assert profile.status_code == 200, profile.text[:200]\n"
                        "assert 'rohitsharma@hygaar.com' in profile.text\n"
                        "billing=client.get('/billing')\n"
                        "assert billing.status_code == 200, billing.text[:200]\n"
                        "assert 'Reachly Pro' in billing.text\n"
                    ),
                ],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_hosted_scheduler_separates_social_instagram_and_medium_slots(self):
        from server.db import User
        from server.orchestrator import scheduled_actions_for_user

        user = User(
            telegram_chat_id="42",
            post_times="09:00,13:30,21:00",
            instagram_offset_minutes=5,
            medium_times="09:30,14:30,19:30",
        )

        self.assertEqual(scheduled_actions_for_user(user, "09:00"), ["linkedin"])
        self.assertEqual(scheduled_actions_for_user(user, "09:05"), ["instagram"])
        self.assertEqual(scheduled_actions_for_user(user, "09:30"), ["medium"])
        self.assertEqual(scheduled_actions_for_user(user, "13:35"), ["instagram"])
        self.assertEqual(scheduled_actions_for_user(user, "22:00"), [])

    def test_saas_orchestrator_maps_linkedin_organization_id(self):
        from reachly.models import Platform, PlatformMode
        from server.orchestrator import _creds_from_secrets

        creds = _creds_from_secrets(
            Platform.linkedin,
            PlatformMode.api,
            {
                "access_token": "token",
                "organization_id": "123456",
            },
        )

        self.assertEqual(creds.extra["organization_id"], "123456")

    def test_otp_code_is_six_digits(self):
        from server.telegram_bot import secrets

        with patch.object(secrets, "randbelow", return_value=7):
            self.assertEqual(f"{secrets.randbelow(1_000_000):06d}", "000007")

    def test_admin_telegram_id_is_active_in_production_without_free_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "reachly.db"
            env = os.environ.copy()
            env["REACHLY_DATABASE_URL"] = f"sqlite:///{db_path}"
            env["REACHLY_ENVIRONMENT"] = "production"
            env["REACHLY_FREE_MODE"] = "false"
            env["REACHLY_SESSION_SECRET"] = "test-session-secret"
            env["REACHLY_VAULT_KEY"] = "AbCdEfGhIjKlMnOpQrStUvWxYz01234567890123456="
            env["REACHLY_ADMIN_TELEGRAM_IDS"] = "42"
            proc = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "from server.db import init_db, get_session, User\n"
                        "from server.telegram_bot import TelegramBot\n"
                        "init_db()\n"
                        "TelegramBot.send_message=lambda self, chat_id, text: True\n"
                        "TelegramBot('123:test')._on_start('42', 'alice')\n"
                        "with get_session() as s:\n"
                        "    user=s.get(User, 1)\n"
                        "    assert user.is_active and user.plan == 'pro'\n"
                    ),
                ],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_telegram_otp_flow_consumes_code_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "reachly.db"
            env = os.environ.copy()
            env["REACHLY_DATABASE_URL"] = f"sqlite:///{db_path}"
            env["REACHLY_TELEGRAM_BOT_TOKEN"] = "123:test"
            proc = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import re\n"
                        "from server.db import init_db, get_session, User\n"
                        "from server import telegram_bot as tb\n"
                        "init_db()\n"
                        "with get_session() as s:\n"
                        "    s.add(User(telegram_chat_id='42', telegram_username='alice', is_active=True))\n"
                        "    s.commit()\n"
                        "sent=[]\n"
                        "tb.TelegramBot.send_message=lambda self, chat_id, text: sent.append(text) or True\n"
                        "ok,msg=tb.generate_and_send_otp('@alice')\n"
                        "assert ok, msg\n"
                        "code=re.search(r'<b>(\\d{6})</b>', sent[0]).group(1)\n"
                        "ok,user_id=tb.verify_otp('@alice', code)\n"
                        "assert ok and user_id\n"
                        "ok_again,_=tb.verify_otp('@alice', code)\n"
                        "assert not ok_again\n"
                    ),
                ],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
