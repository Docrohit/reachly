from reachly.content import generate_post
from reachly.models import BusinessProfile


class FakeLLM:
    def __init__(self):
        self.prompt = ""

    def generate_json(self, system_prompt, user_prompt):
        self.prompt = user_prompt
        return {
            "theme": "catalog ops",
            "hook": "A better PDP starts before the render",
            "body": "Teams improve faster when creative operations and product data share one source of truth.",
            "hashtags": ["#ecommerce"],
            "image_prompt": "A clean ecommerce operations desk",
            "cta_link": None,
        }


def test_generate_post_uses_performance_and_newness_context():
    llm = FakeLLM()
    business = BusinessProfile(name="Reachly", default_hashtags=["#Reachly"])

    generate_post(
        llm,
        business,
        theme="catalog ops",
        performance_context="- linkedin | impressions=1200 | likes=38",
        newness_context="linkedin last 3 posts:\n  - workflow: Old hook",
    )

    assert "RECENT PERFORMANCE / ANALYTICS CONTEXT" in llm.prompt
    assert "impressions=1200" in llm.prompt
    assert "LAST 3 POSTS BY PLATFORM" in llm.prompt
    assert "Old hook" in llm.prompt
