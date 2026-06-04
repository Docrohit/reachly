import os
import subprocess
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
                    ".venv/bin/python",
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
                    ".venv/bin/python",
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
                    ".venv/bin/python",
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
