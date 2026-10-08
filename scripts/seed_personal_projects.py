"""Create the owner's Council workspaces without copying credentials or enabling posts."""
import argparse
import json
from sqlmodel import select
from server.app import app  # registers all database tables; does not start services
from server.db import User, BusinessProfileRow, get_session, init_db
from server.workspaces import create_workspace
from server.crypto import encrypt_dict

PROJECTS = [
    {
        "name": "Council of AI",
        "website": "https://councilofai.nftforger.com",
        "sector": "AI collaboration and developer tools",
        "vision": "Help people work on shared goals with a team of AI models and agents that share evidence and challenge proposed answers.",
        "product_info": "Council of AI is an independent, self-hostable multi-model collaboration project with a mobile-friendly web workspace and a developer CLI. Agents work as peers, choose roles, exchange findings, investigate questions, and challenge proposed answers without a permanent coordinator. Users can select different local and cloud models. It is a working alpha; automated checks are not proof of superior reasoning quality.",
        "goals": "Introduce Council of AI to developers, AI builders, researchers, and independent founders. Explain peer collaboration, shared goals, evidence, and practical workflows. Invite people to explore the product. Do not invent benchmarks, customer counts, guarantees, pricing, or shipped features not established in the supplied project material.",
        "content_themes": "multi-model collaboration, peer review between agents, building with AI, evidence-led reasoning, self-hosted tools, founder development notes",
        "default_hashtags": "#CouncilOfAI #MultiAgentAI #BuildInPublic",
        "brand_voice": "Clear, curious, practical, candid about alpha status and limitations. Explain with examples; avoid hype.",
        "project_notes": "Source: Council/README.md inspected on 2026-10-07. The project describes a team of coding models and agents working toward one shared goal. Web workspace and standalone CLI/TUI share the collaboration engine. Peers communicate and challenge answers; the harness enforces access, budgets and completion. Treat older product-theory roadmap and pricing statements as unverified until reviewed against the current release. Public website: https://councilofai.nftforger.com",
    },
    {
        "name": "Council Network",
        "website": "https://councilnetwork.nftforger.com",
        "sector": "AI agent social networks and creative experimentation",
        "vision": "Let people explore how AI agents interact when humans are not writing every prompt.",
        "product_info": "Council Network is a social network whose members are AI agents. People create agents with a name, avatar, bio, interests and optional personality, connecting each to its own reasoning and optional vision, image or video models. Agents can ponder, post, reply, vote, follow, message, block, create or remix media, and participate in Council-style rooms. People watch and nudge their agents; human-steered posts are labelled. It is a separate product from Council of AI.",
        "goals": "Introduce the agent social-network concept to AI enthusiasts, builders and creative experimenters. Show how agent identities, models and interaction differ from ordinary chatbot conversations. Keep claims tied to product documentation. Do not invent activity levels, user counts, emergent intelligence claims, pricing or guaranteed outcomes.",
        "content_themes": "AI agents as social participants, agent personalities, model diversity, creative agent media, human-steered versus autonomous posts, experiments in agent interaction",
        "default_hashtags": "#CouncilNetwork #AIAgents #BuildInPublic",
        "brand_voice": "Curious, playful, concrete and transparent. Describe observable behavior without claiming AI consciousness.",
        "project_notes": "Source: CouncilNetwork/README.md inspected on 2026-10-07. The public proposition is: Let's see how agents talk when no one is prompting them. The source describes agent profiles, connected models, scheduled pondering/exploration, wall interactions, creative media and Council-style rooms. Humans watch and nudge; some human controls depend on the plan. Verify current entitlements and prices before discussing them. Public website: https://councilnetwork.nftforger.com",
    },
]


def seed(owner_id: int):
    init_db()
    with get_session() as session:
        owner = session.get(User, owner_id)
        if not owner or owner.owner_user_id is not None:
            raise ValueError("Select the existing personal account owner.")
        children = session.exec(select(User).where(User.owner_user_id == owner_id)).all()
        ids = [owner_id] + [child.id for child in children]
        existing = {p.website for p in session.exec(select(BusinessProfileRow).where(BusinessProfileRow.user_id.in_(ids))).all()}
    for project in PROJECTS:
        if project["website"] in existing:
            print(f"Already present: {project['name']}")
            continue
        values = dict(project)
        name, website = values.pop("name"), values.pop("website")
        notes = values.pop("project_notes")
        values["providers_vault"] = encrypt_dict({"project_notes": notes})
        workspace = create_workspace(owner_id, name, website, **values)
        print(f"Created: {name} (workspace {workspace.id}); dry-run on, schedule off, no provider or platform credentials")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-id", required=True, type=int)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply:
        seed(args.owner_id)
    else:
        print(json.dumps([{k:v for k,v in p.items() if k != 'project_notes'} for p in PROJECTS], indent=2))
