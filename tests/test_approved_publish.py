import hashlib
import tempfile
import uuid
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch, Mock
from reachly.approved_publish import publish
from reachly.models import Platform, PostResult


class ApprovedPublishTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.media = self.root / "media"
        self.media.mkdir()
        (self.media / "approved.png").write_bytes(b"test-reviewed-media")
        self.connection = str(uuid.uuid4())
        self.payload = {"request_id": str(uuid.uuid4()), "connection_id": self.connection,
            "clinic_id": "HYC-DEMO", "platform": "instagram", "account": "demo_clinic",
            "caption": "Approved caption\n\n#clinic", "media_name": "approved.png",
            "media_sha256": hashlib.sha256(b"test-reviewed-media").hexdigest()}
        self.bindings = {self.connection: {"clinic_id": "HYC-DEMO", "platform": "instagram", "account": "demo_clinic"}}

    def send(self):
        return publish(self.payload, bindings=self.bindings, data_root=self.root / "sessions", media_root=self.media)

    @patch("reachly.approved_publish.get_poster")
    def test_exact_payload_and_idempotent_receipt(self, factory):
        factory.return_value.post.return_value = PostResult(platform=Platform.instagram, ok=True)
        receipt = self.send()
        self.assertEqual(receipt["status"], "published")
        self.assertEqual(self.send(), receipt)
        factory.return_value.post.assert_called_once()
        post = factory.return_value.post.call_args.args[0]
        self.assertEqual(post.for_platform(Platform.instagram), self.payload["caption"])
        self.assertEqual(factory.call_args.kwargs["data_dir"].name, self.connection)

    @patch("reachly.approved_publish.get_poster")
    def test_crash_after_claim_never_repeats_post(self, factory):
        factory.return_value.post.side_effect = RuntimeError("browser terminated")
        with self.assertRaises(RuntimeError):
            self.send()
        self.assertEqual(self.send()["status"], "needs_attention")
        factory.return_value.post.assert_called_once()

    @patch("reachly.approved_publish.get_poster")
    def test_modified_payload_cannot_reuse_request(self, factory):
        factory.return_value.post.return_value = PostResult(platform=Platform.instagram, ok=True)
        self.send()
        self.payload["caption"] = "Changed caption"
        with self.assertRaises(ValueError):
            self.send()
        factory.return_value.post.assert_called_once()

    def test_cross_clinic_and_account_binding_rejected(self):
        self.payload["clinic_id"] = "another-clinic"
        with self.assertRaises(ValueError):
            self.send()
        self.payload["clinic_id"] = "HYC-DEMO"
        self.payload["account"] = "another_account"
        with self.assertRaises(ValueError):
            self.send()

    def test_changed_media_and_path_escape_rejected(self):
        (self.media / "approved.png").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.send()
        self.payload["media_name"] = "../outside.png"
        with self.assertRaises(ValueError):
            self.send()

    @patch("reachly.approved_publish.get_poster")
    def test_failed_publish_not_automatically_retried(self, factory):
        factory.return_value.post.return_value = PostResult(platform=Platform.instagram, ok=False, error="Uncertain")
        self.assertEqual(self.send()["status"], "needs_attention")
        self.assertEqual(self.send()["status"], "needs_attention")
        factory.return_value.post.assert_called_once()
