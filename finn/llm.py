"""Model calls: structured output, two cost tiers, and a permanent result cache (filings never change).
Claude through its SDK, or open-weight models on any OpenAI-compatible server (Groq, OpenRouter, a local Ollama)."""
import hashlib
import json
import time

import anthropic
import requests
from pydantic import BaseModel

from . import store
from .config import CLAUDE, LLM_KEY, LLM_URL, MODELS

EFFORT = {"fast": "low", "deep": "medium"}
CAP = {"fast": 3000, "deep": 4500}  # output tokens per open-model call: prompt + cap fit an 8K tokens/minute free tier
_client: anthropic.Anthropic | None = None


def available() -> bool:
    return CLAUDE or bool(LLM_URL)


def ask[T: BaseModel](tier: str, system: str, prompt: str, schema: type[T], max_tokens: int = 16000) -> T | None:
    """A validated `schema` instance, or None if no model is configured or the model declines."""
    signature = json.dumps(schema.model_json_schema(), sort_keys=True)
    key = hashlib.sha256("\x1f".join((MODELS[tier], system, prompt, signature)).encode()).hexdigest()
    if (hit := store.get("llm", key)) is not None:
        return schema.model_validate(hit["output"])
    if not available():
        return None
    parsed, usage = (_claude if CLAUDE else _open)(tier, system, prompt, schema, max_tokens)
    if parsed is not None:
        store.put("llm", key, {"output": parsed.model_dump(), **usage})
    return parsed


def _claude(tier, system, prompt, schema, max_tokens):
    global _client
    _client = _client or anthropic.Anthropic()
    # Server-side fallback re-runs a declined request on another model (supported on the Opus tier, not on Haiku).
    fallback = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"} if tier == "deep" else {}
    r = _client.beta.messages.parse(
        model=MODELS[tier], max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": prompt}],
        output_format=schema, output_config={"effort": EFFORT[tier]}, **fallback)
    usage = {"model": r.model, "input_tokens": r.usage.input_tokens, "output_tokens": r.usage.output_tokens}
    return (r.parsed_output if r.stop_reason == "end_turn" else None), usage


def _closed(node):
    """The JSON Schema subset that strict mode accepts: every object closed, every field required."""
    if isinstance(node, list):
        return [_closed(n) for n in node]
    if not isinstance(node, dict):
        return node
    out = {k: {name: _closed(s) for name, s in v.items()} if k in ("properties", "$defs") else _closed(v)
           for k, v in node.items() if k != "title"}
    if "properties" in out:
        out |= {"required": list(out["properties"]), "additionalProperties": False}
    return out


def _open(tier, system, prompt, schema, max_tokens):
    """Strict JSON-schema output where the server supports it, otherwise JSON mode with the schema in the prompt."""
    model, shape = MODELS[tier], _closed(schema.model_json_schema())
    body = {"model": model, "max_tokens": min(max_tokens, CAP[tier]),
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "response_format": {"type": "json_schema", "json_schema": {"name": schema.__name__, "schema": shape, "strict": True}}}
    if "gpt-oss" in model:
        body["reasoning_effort"] = EFFORT[tier]
    for attempt in range(10):
        try:
            r = requests.post(f"{LLM_URL}/chat/completions", json=body, timeout=180,
                              headers={"Authorization": f"Bearer {LLM_KEY}"} if LLM_KEY else {})
        except (requests.ConnectionError, requests.Timeout):  # a dropped or stalled connection is worth another try
            if attempt == 9:
                raise
            time.sleep(2)
            continue
        if r.status_code == 429:  # free tiers cap tokens per minute: wait as long as the server asks
            if (wait := float(r.headers.get("retry-after", 10))) > 60:  # a daily cap: say so instead of hanging
                break
            time.sleep(wait)
        elif r.status_code == 400 and body["response_format"]["type"] == "json_schema":
            body["response_format"] = {"type": "json_object"}
            body["messages"][0]["content"] = f"{system}\n\nReply with one JSON object following this JSON Schema:\n{json.dumps(shape)}"
        else:
            break
    if not r.ok:
        raise RuntimeError(f"{model}: HTTP {r.status_code} {r.text[:300]}")
    data = r.json()
    choice, used = data["choices"][0], data.get("usage", {})
    usage = {"model": model, "input_tokens": used.get("prompt_tokens"), "output_tokens": used.get("completion_tokens")}
    text = choice["message"].get("content") or ""
    try:  # a reply cut short, or one that ignores the schema, counts as declining
        return (schema.model_validate_json(text[text.index("{"): text.rindex("}") + 1])
                if choice.get("finish_reason") == "stop" else None), usage
    except ValueError:
        return None, usage
