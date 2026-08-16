from unittest.mock import patch
import zipfile

from reachly.agent import Agent, AgentSettings
from reachly.config import AgentConfig
from reachly.context import load_strategy_context
from reachly.knowledge_bank import KnowledgeEvent, append_knowledge_event
from reachly.models import BusinessProfile, GeneratedPost


def _write_minimum_repo(repo):
    (repo / "AGENTS.md").write_text("Agent constitution: current capabilities.", encoding="utf-8")
    (repo / "product_theory.md").write_text("Product theory: current positioning.", encoding="utf-8")


def _write_docx(path, text):
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"
        "</w:body>"
        "</w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", xml)


def test_strategy_context_auto_loads_moat_and_business_cases(tmp_path):
    repo = tmp_path / "repo"
    docs = repo / "docs"
    docs.mkdir(parents=True)
    _write_minimum_repo(repo)
    (docs / "HYGAAR_MOAT_ARCHITECTURE_2026.md").write_text(
        "Moat: satellite intelligence and fine-detail preservation.",
        encoding="utf-8",
    )
    (repo / "Business_cases_may28_latest.csv").write_text(
        "Business cases,Use Case\nFlatlay to Studio,Fashion catalog automation\n",
        encoding="utf-8",
    )

    context = load_strategy_context(data_dir=tmp_path / "data", context_repo=str(repo))
    prompt = context.for_prompt()

    assert context.source == "repo+supporting_docs"
    assert "Hygaar moat architecture" in prompt
    assert "satellite intelligence" in prompt
    assert "Hygaar business cases" in prompt
    assert "Flatlay to Studio" in prompt


def test_strategy_context_accepts_explicit_extra_docs(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_minimum_repo(repo)
    extra = tmp_path / "Real Moats.txt"
    extra.write_text("Real moat: workflow depth compounds over time.", encoding="utf-8")

    context = load_strategy_context(
        data_dir=tmp_path / "data",
        context_repo=str(repo),
        extra_doc_paths=[str(extra)],
    )

    assert "Real moat: workflow depth" in context.for_prompt()


def test_strategy_context_accepts_docx_extra_docs(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_minimum_repo(repo)
    extra = tmp_path / "Real Moats.docx"
    _write_docx(extra, "Real moat: QC correction logic and brand-specific operational knowledge.")

    context = load_strategy_context(
        data_dir=tmp_path / "data",
        context_repo=str(repo),
        extra_doc_paths=[str(extra)],
    )

    assert "QC correction logic" in context.for_prompt()


def test_strategy_context_reads_knowledge_bank(tmp_path):
    data_dir = tmp_path / "data"
    append_knowledge_event(
        data_dir,
        KnowledgeEvent(
            title="Prod release",
            summary="Added long-form narration-led video generation for LinkedIn and YouTube.",
            source="github_actions",
            environment="prod",
            commit_sha="abc123",
        ),
    )

    context = load_strategy_context(data_dir=data_dir)
    prompt = context.for_prompt()

    assert context.source == "knowledge_bank"
    assert "Reachly knowledge bank" in prompt
    assert "long-form narration-led video" in prompt


def test_agent_refreshes_strategy_context_before_each_post(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_minimum_repo(repo)
    agents = repo / "AGENTS.md"
    agents.write_text("Agent constitution: old feature set.", encoding="utf-8")
    captured = []

    def fake_generate_post(*args, strategy=None, **kwargs):
        captured.append(strategy.for_prompt())
        return GeneratedPost(theme="theme", hook="hook", body="body")

    agent = Agent(
        BusinessProfile(name="Hygaar", content_themes=["theme"]),
        {},
        AgentSettings(data_dir=tmp_path / "data", context_repo=str(repo)),
    )
    with patch("reachly.agent.generate_post", side_effect=fake_generate_post):
        agent.build_post()
        agents.write_text("Agent constitution: new merged feature.", encoding="utf-8")
        agent.build_post()

    assert "old feature set" in captured[0]
    assert "new merged feature" in captured[1]
    agent.close()


def test_config_reads_context_docs_env_value(tmp_path):
    doc = tmp_path / "moat.md"
    doc.write_text("Moat doc", encoding="utf-8")

    cfg = AgentConfig({"REACHLY_CONTEXT_DOCS": str(doc)})

    assert cfg.context_doc_paths == [str(doc)]
