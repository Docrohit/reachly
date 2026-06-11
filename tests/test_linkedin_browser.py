from reachly.platforms.linkedin import _normalize_text, _text_probe


def test_linkedin_text_probe_is_stable_across_whitespace():
    text = "First line\n\nSecond   line\twith spacing"

    assert _normalize_text(text) == "First line Second line with spacing"
    assert _text_probe(text) == "First line Second line with spacing"
