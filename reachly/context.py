"""Load strategy context for content generation.

Priority:
  1. Goals from the dashboard (`goals.md` in the data directory)
  2. Fallback: `AGENTS.md` + `product_theory.md` from the client's repo

For Hygaar the repo is typically `hdb_backend/` (or the monorepo root). Other
customers set `REACHLY_CONTEXT_REPO` to their product repo path.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("reachly.context")

MAX_FILE_CHARS = 12_000  # per file, keep prompts bounded


@dataclass
class StrategyContext:
    """Text injected into the LLM prompt."""

    source: str  # "goals" | "repo_docs" | "goals+repo" | "none"
    goals_text: str = ""
    agents_excerpt: str = ""
    product_theory_excerpt: str = ""
    posting_style: str = "thought_leader"  # thought_leader | brand_promoter

    def for_prompt(self) -> str:
        parts: list[str] = []
        if self.goals_text.strip():
            parts.append("## Business goals (from dashboard — highest priority)\n" + self.goals_text.strip())
        if self.agents_excerpt.strip():
            parts.append("## Product constitution (AGENTS.md excerpt)\n" + self.agents_excerpt.strip())
        if self.product_theory_excerpt.strip():
            parts.append("## Product theory (why we exist — excerpt)\n" + self.product_theory_excerpt.strip())
        if not parts:
            return ""
        style = (
            "Write as a credible industry THOUGHT LEADER: insights first, soft brand tie-in."
            if self.posting_style == "thought_leader"
            else "Write as a passionate PROMOTER of this product: educate the market on what "
            "the platform does and why it matters, still useful and non-spammy."
        )
        return (
            "\n\n".join(parts)
            + f"\n\n## Posting mode\n{style}\n"
            + "Use the above to stay accurate on product capabilities and positioning. "
            "Do not invent features not described above."
        )


def _read_truncated(path: Path) -> str:
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) > MAX_FILE_CHARS:
        return text[:MAX_FILE_CHARS] + "\n\n[... truncated for prompt size ...]"
    return text


def find_repo_docs(repo: Path) -> tuple[Optional[Path], Optional[Path]]:
    """Locate AGENTS.md and product_theory.md in repo or parents (up to 3 levels)."""
    candidates = [repo, *list(repo.parents)[:3]]
    for base in candidates:
        agents = base / "AGENTS.md"
        theory = base / "product_theory.md"
        if agents.is_file() and theory.is_file():
            return agents, theory
        # common layout: docs live in hdb_backend subfolder
        sub = base / "hdb_backend"
        if sub.is_dir():
            a2, t2 = sub / "AGENTS.md", sub / "product_theory.md"
            if a2.is_file() and t2.is_file():
                return a2, t2
    return None, None


def load_strategy_context(
    *,
    data_dir: Path,
    context_repo: Optional[str] = None,
    agents_path: Optional[str] = None,
    product_theory_path: Optional[str] = None,
    posting_style: str = "thought_leader",
) -> StrategyContext:
    data_dir = Path(data_dir)
    goals_file = data_dir / "goals.md"
    goals_text = _read_truncated(goals_file) if goals_file.is_file() else ""

    agents_excerpt = ""
    theory_excerpt = ""
    source = "none"

    if goals_text.strip():
        source = "goals"

    # Always try to load repo docs when paths are configured (merge with goals).
    agents_p = Path(agents_path) if agents_path else None
    theory_p = Path(product_theory_path) if product_theory_path else None

    if not (agents_p and agents_p.is_file()) or not (theory_p and theory_p.is_file()):
        if context_repo:
            a, t = find_repo_docs(Path(context_repo).expanduser())
            agents_p = agents_p or a
            theory_p = theory_p or t

    if agents_p and agents_p.is_file():
        agents_excerpt = _read_truncated(agents_p)
        logger.info("Loaded AGENTS.md from %s", agents_p)
    if theory_p and theory_p.is_file():
        theory_excerpt = _read_truncated(theory_p)
        logger.info("Loaded product_theory.md from %s", theory_p)

    if agents_excerpt or theory_excerpt:
        source = "goals+repo" if goals_text.strip() else "repo_docs"

    return StrategyContext(
        source=source,
        goals_text=goals_text,
        agents_excerpt=agents_excerpt,
        product_theory_excerpt=theory_excerpt,
        posting_style=posting_style,
    )
