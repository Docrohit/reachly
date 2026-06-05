import unittest
from datetime import datetime, timedelta, timezone

from reachly.agent import Agent, AgentSettings
from reachly.models import BusinessProfile, GeneratedPost


class EngagementPersistenceTests(unittest.TestCase):
    def test_due_engagement_survives_agent_recreation(self):
        with self.subTest("pending job is not run before its due time"):
            agent = self._agent()
            post = self._post()
            run_at = datetime.now(timezone.utc) + timedelta(minutes=30)
            agent.schedule_linkedin_engagement(run_at, post)
            agent.engage_after_linkedin_post = lambda: 1
            self.assertEqual(agent.run_due_engagement(now=run_at - timedelta(seconds=1)), 0)
            agent.close()

        recreated = self._agent()
        calls = []

        def fake_engage():
            calls.append(True)
            return 2

        recreated.engage_after_linkedin_post = fake_engage
        self.assertEqual(recreated.run_due_engagement(now=run_at), 2)
        self.assertEqual(len(calls), 1)
        self.assertEqual(recreated.run_due_engagement(now=run_at + timedelta(minutes=1)), 0)
        recreated.close()

    def _agent(self) -> Agent:
        import tempfile

        if not hasattr(self, "_tmp"):
            self._tmp = tempfile.TemporaryDirectory()
        return Agent(
            BusinessProfile(name="Hygaar"),
            {},
            AgentSettings(data_dir=self._tmp.name, dry_run=True),
        )

    def _post(self) -> GeneratedPost:
        return GeneratedPost(
            theme="customer wins",
            hook="A cleaner product launch workflow starts before the photoshoot.",
            body="Use AI to plan variants before campaign production starts.",
            hashtags=["#AI", "#ecommerce"],
        )

    def tearDown(self):
        tmp = getattr(self, "_tmp", None)
        if tmp:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
