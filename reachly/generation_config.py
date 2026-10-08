"""Operator-provisioned client scopes and credential profiles, never request keys."""
import json
import os
from pathlib import Path


def configuration():
    path = os.getenv("REACHLY_GENERATION_CONFIG")
    if not path:
        raise ValueError("Generation service is not configured")
    return json.loads(Path(path).read_text())


def provider_settings(profile):
    values = configuration()["providers"][profile]
    result = {key: values[key] for key in ("llm_provider", "llm_model", "image_model")}
    for key in ("gemini_api_key", "openai_api_key", "anthropic_api_key"):
        result[key] = os.getenv(values.get(key + "_env", ""), "")
    if not result["gemini_api_key"] or not result.get(result["llm_provider"] + "_api_key"):
        raise ValueError("Selected generation credential profile is incomplete")
    return result
