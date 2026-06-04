"""Thin multi-provider LLM client used for text content generation.

Supports Gemini, OpenAI and Anthropic. Only the provider you select needs its
SDK installed and key configured. Returns plain strings (optionally JSON).
"""
from __future__ import annotations

import json as _json
import logging
from typing import Optional

logger = logging.getLogger("reachly.llm")

_DEFAULT_MODELS = {
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-sonnet-latest",
}


class LLMClient:
    def __init__(
        self,
        provider: str,
        *,
        model: Optional[str] = None,
        gemini_api_key: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        anthropic_api_key: Optional[str] = None,
    ):
        self.provider = provider.lower()
        self.model = model or _DEFAULT_MODELS.get(self.provider)
        self._gemini_key = gemini_api_key
        self._openai_key = openai_api_key
        self._anthropic_key = anthropic_api_key

    # ---- public API ---------------------------------------------------
    def generate(self, system: str, prompt: str, *, as_json: bool = False) -> str:
        if self.provider == "gemini":
            text = self._gemini(system, prompt)
        elif self.provider == "openai":
            text = self._openai(system, prompt)
        elif self.provider == "anthropic":
            text = self._anthropic(system, prompt)
        else:
            raise ValueError(f"Unknown LLM provider: {self.provider}")
        return _strip_json_fences(text) if as_json else text

    def generate_json(self, system: str, prompt: str) -> dict:
        raw = self.generate(system, prompt, as_json=True)
        try:
            return _json.loads(raw)
        except _json.JSONDecodeError:
            # Last-ditch: pull the first {...} block out of the text.
            start, end = raw.find("{"), raw.rfind("}")
            if start != -1 and end != -1:
                return _json.loads(raw[start : end + 1])
            raise

    # ---- providers ----------------------------------------------------
    def _gemini(self, system: str, prompt: str) -> str:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self._gemini_key)
        resp = client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(system_instruction=system),
        )
        return (resp.text or "").strip()

    def _openai(self, system: str, prompt: str) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=self._openai_key)
        resp = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=0.8,
        )
        return (resp.choices[0].message.content or "").strip()

    def _anthropic(self, system: str, prompt: str) -> str:
        import anthropic

        client = anthropic.Anthropic(api_key=self._anthropic_key)
        resp = client.messages.create(
            model=self.model,
            max_tokens=1500,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip()


def _strip_json_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1] if "\n" in t else t
        if t.endswith("```"):
            t = t[: -3]
        # remove a leading "json" tag
        if t.lstrip().startswith("json"):
            t = t.lstrip()[4:]
    return t.strip()
