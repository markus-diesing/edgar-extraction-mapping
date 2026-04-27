"""
Underlying Data Module — LLM backend dispatcher.

Supports three providers:
  anthropic          — Anthropic Messages API (raw httpx, no SDK)
  openai-compatible  — /v1/chat/completions (LM Studio, Ollama compat, OpenAI)
  ollama             — Ollama /api/chat native endpoint

Call ``call_underlying_llm(system_prompt, user_prompt, cfg)`` to dispatch.
Returns ``(raw_text: str, input_tokens: int, output_tokens: int)``.

The extractor owns all prompt construction and JSON parsing; this module
handles only the HTTP layer and response-text cleanup.

Design notes
------------
* ``/no_think`` is appended to the system prompt for non-Anthropic providers
  to suppress Qwen3 chain-of-thought blocks (harmless for other models).
* OpenAI-compatible providers are tried with three ``response_format`` levels:
  ``json_schema`` → ``json_object`` → none.  A 400 on the strictest level
  cascades to the next, which is the observed behaviour for LM Studio MLX.
* ``try_repair_json`` applies suffix-injection repair for the LM Studio MLX
  truncation bug (finish_reason="stop" despite incomplete JSON output).
* Token counts are extracted from provider-specific response fields:
    - Anthropic        → usage.input_tokens / output_tokens
    - OpenAI-compat    → usage.prompt_tokens / completion_tokens
    - Ollama           → prompt_eval_count / eval_count
"""
from __future__ import annotations

import contextlib
import json
import logging
import re
import time
from dataclasses import dataclass

import httpx

import config

log = logging.getLogger(__name__)

_TIMEOUT = 120.0   # 14B MLX models can be slow — generous headroom
_MAX_TOKENS = 1_024
_ANTHROPIC_VERSION = "2023-06-01"

# ---------------------------------------------------------------------------
# Provider endpoint defaults
# ---------------------------------------------------------------------------

PROVIDER_DEFAULTS: dict[str, str] = {
    "anthropic":         "https://api.anthropic.com",
    "openai-compatible": "http://192.168.210.239:1234",
    "ollama":            "http://localhost:11434",
}

# ---------------------------------------------------------------------------
# LlmConfig
# ---------------------------------------------------------------------------


@dataclass
class LlmConfig:
    """Resolved LLM backend configuration for one extraction call."""
    provider: str          # "anthropic" | "openai-compatible" | "ollama"
    endpoint: str          # base URL (trailing slash stripped at access time)
    model:    str          # model identifier string
    api_key:  str = ""     # required for Anthropic; optional for OAI-compat

    @property
    def base_url(self) -> str:
        url = self.endpoint or PROVIDER_DEFAULTS.get(self.provider, "")
        return url.rstrip("/")


def load_config() -> LlmConfig:
    """Build an ``LlmConfig`` from the current ``runtime_settings.yaml``."""
    import settings_store  # lazy import — avoids circular dependency
    s = settings_store.get_settings()
    provider  = s.get("underlying_llm_provider", "anthropic")
    endpoint  = s.get("underlying_llm_endpoint", "")
    model_raw = s.get("underlying_llm_model",    "")
    api_key   = s.get("underlying_llm_api_key",  "")

    if provider == "anthropic":
        # For Anthropic, always mirror the active Filings model so both pipelines
        # stay in sync.  The underlying_llm_model key is intentionally ignored
        # when the provider is Anthropic — the UI reflects this by hiding the
        # model field and pointing the user to the Filings configuration section.
        model_raw = s.get("claude_model") or config.CLAUDE_MODEL_DEFAULT
        # Force endpoint to empty so base_url falls through to PROVIDER_DEFAULTS
        # ("https://api.anthropic.com"). A previously saved local URL such as
        # "http://localhost:1234" must not bleed into the Anthropic call.
        endpoint = ""
    elif not model_raw:
        # Local providers: fall back to sensible defaults when nothing is set
        model_raw = "qwen3-14b-mlx" if provider == "openai-compatible" else "llama3"

    return LlmConfig(provider=provider, endpoint=endpoint,
                     model=model_raw, api_key=api_key)


# ---------------------------------------------------------------------------
# Response text cleanup
# ---------------------------------------------------------------------------

def clean_response(text: str) -> str:
    """Strip Qwen3 ``<think>`` blocks and markdown fences from a raw response."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    return text.strip()


# Ordered suffixes used by try_repair_json.
# Goal: close the most common truncation points in the three-key underlying schema.
#   {"fields": {…}, "confidence": {…}, "excerpts": {…}}
# Most truncations happen mid-string inside "excerpts" (longest generated block)
# or mid-"brief_description" inside "fields".
_REPAIR_SUFFIXES: list[str] = [
    "",       # already valid — no-op
    '"}}',    # truncated mid-string in a nested object → close string + obj + root
    '"}}}}',  # two levels deep (e.g. inside excerpts sub-key value)
    '"}}}',
    '"}}',
    '}}',
    '}',
]


def try_repair_json(raw: str) -> dict | None:
    """
    Attempt suffix-injection repair on a truncated JSON string.

    LM Studio MLX occasionally truncates generated content and reports
    ``finish_reason: "stop"`` anyway.  We try common closing suffixes to
    recover whatever fields were already fully generated.

    Returns the parsed ``dict`` on success, ``None`` if all attempts fail.
    """
    for suffix in _REPAIR_SUFFIXES:
        with contextlib.suppress(json.JSONDecodeError, ValueError):
            data = json.loads(raw + suffix)
            if isinstance(data, dict):
                return data
    return None


# ---------------------------------------------------------------------------
# JSON schema for OpenAI-compatible structured output
# ---------------------------------------------------------------------------

_NULL_STR  = {"anyOf": [{"type": "string"},  {"type": "null"}]}
_NULL_BOOL = {"anyOf": [{"type": "boolean"}, {"type": "null"}]}
_FIELDS_SCHEMA = {
    "type": "object",
    "properties": {
        "legal_name":        _NULL_STR,
        "share_class_name":  _NULL_STR,
        "share_type":        _NULL_STR,
        "brief_description": _NULL_STR,
        "adr_flag":          _NULL_BOOL,
    },
    "required": ["legal_name", "share_class_name", "share_type",
                 "brief_description", "adr_flag"],
    "additionalProperties": False,
}
_CONF_SCHEMA = {
    "type": "object",
    "properties": {k: {"type": "number"} for k in
                   ["legal_name", "share_class_name", "share_type",
                    "brief_description", "adr_flag"]},
    "required": ["legal_name", "share_class_name", "share_type",
                 "brief_description", "adr_flag"],
    "additionalProperties": False,
}
_EXCERPT_SCHEMA = {
    "type": "object",
    "properties": {k: {"type": "string"} for k in
                   ["legal_name", "share_class_name", "share_type",
                    "brief_description", "adr_flag"]},
    "required": ["legal_name", "share_class_name", "share_type",
                 "brief_description", "adr_flag"],
    "additionalProperties": False,
}
_UNDERLYING_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "fields":     _FIELDS_SCHEMA,
        "confidence": _CONF_SCHEMA,
        "excerpts":   _EXCERPT_SCHEMA,
    },
    "required": ["fields", "confidence", "excerpts"],
    "additionalProperties": False,
}

# ---------------------------------------------------------------------------
# Provider-specific callers
# ---------------------------------------------------------------------------


def _call_anthropic(
    system_prompt: str, user_prompt: str, cfg: LlmConfig,
) -> tuple[str, int, int]:
    url = cfg.base_url + "/v1/messages"
    headers = {
        "x-api-key":         cfg.api_key or config.ANTHROPIC_API_KEY,
        "anthropic-version": _ANTHROPIC_VERSION,
        "content-type":      "application/json",
    }
    payload = {
        "model":      cfg.model,
        "max_tokens": _MAX_TOKENS,
        "system":     system_prompt,
        "messages":   [{"role": "user", "content": user_prompt}],
    }
    resp = httpx.post(url, headers=headers, json=payload, timeout=_TIMEOUT)
    resp.raise_for_status()
    data    = resp.json()
    content = data.get("content") or []
    text    = "".join(b.get("text", "") for b in content if b.get("type") == "text")
    usage   = data.get("usage") or {}
    return text, usage.get("input_tokens", 0), usage.get("output_tokens", 0)


def _call_openai_compatible(
    system_prompt: str, user_prompt: str, cfg: LlmConfig,
) -> tuple[str, int, int]:
    url = cfg.base_url + "/v1/chat/completions"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"

    # Append /no_think to suppress Qwen3 chain-of-thought (harmless on others)
    messages = [
        {"role": "system", "content": system_prompt + " /no_think"},
        {"role": "user",   "content": user_prompt},
    ]

    # Try structured output in descending strictness.
    # LM Studio MLX with "Structured Output" on requires json_schema.
    # Most GGUF / OpenAI endpoints accept json_object.
    # Final fallback: no response_format constraint.
    response_formats = [
        {"type": "json_schema", "json_schema": {
            "name":   "underlying_extraction",
            "strict": True,
            "schema": _UNDERLYING_JSON_SCHEMA,
        }},
        {"type": "json_object"},
        None,
    ]

    for response_format in response_formats:
        payload: dict = {
            "model":      cfg.model,
            "max_tokens": _MAX_TOKENS,
            "messages":   messages,
        }
        if response_format is not None:
            payload["response_format"] = response_format

        resp = httpx.post(url, headers=headers, json=payload, timeout=_TIMEOUT)

        # 400 with a non-None response_format = unsupported format — try next
        if resp.status_code == 400 and response_format is not None:
            log.debug(
                "response_format=%s rejected (400), trying next",
                response_format.get("type"),
            )
            continue

        resp.raise_for_status()
        data    = resp.json()
        choices = data.get("choices") or []
        content = choices[0]["message"]["content"] if choices else ""
        usage   = data.get("usage") or {}
        in_tok  = usage.get("prompt_tokens",    0)
        out_tok = usage.get("completion_tokens", 0)

        # If response_format was requested but the returned content is not valid
        # JSON, try the next (looser) format rather than returning broken text.
        if content and response_format is not None:
            try:
                json.loads(clean_response(content))
            except json.JSONDecodeError:
                log.debug(
                    "response_format=%s returned invalid JSON — trying next",
                    response_format.get("type"),
                )
                continue

        return content, in_tok, out_tok

    return "", 0, 0


def _call_ollama(
    system_prompt: str, user_prompt: str, cfg: LlmConfig,
) -> tuple[str, int, int]:
    url = cfg.base_url + "/api/chat"
    payload = {
        "model":   cfg.model,
        "stream":  False,
        "format":  "json",
        "messages": [
            {"role": "system", "content": system_prompt + " /no_think"},
            {"role": "user",   "content": user_prompt},
        ],
    }
    resp = httpx.post(url, json=payload, timeout=_TIMEOUT)
    resp.raise_for_status()
    data    = resp.json()
    text    = (data.get("message") or {}).get("content", "")
    in_tok  = data.get("prompt_eval_count", 0)
    out_tok = data.get("eval_count",        0)
    return text, in_tok, out_tok


# ---------------------------------------------------------------------------
# Public dispatcher
# ---------------------------------------------------------------------------


def call_underlying_llm(
    system_prompt: str,
    user_prompt:   str,
    cfg:           LlmConfig,
) -> tuple[str, int, int]:
    """Dispatch an LLM call to the configured provider.

    Returns
    -------
    (raw_text, input_tokens, output_tokens)
        ``raw_text`` is the unstripped model response (fences / think-blocks
        are cleaned by :func:`clean_response` in the extractor).
        Token counts are 0 when the provider does not report them.
    """
    log.info(
        "Underlying LLM call: provider=%s model=%s endpoint=%s",
        cfg.provider, cfg.model, cfg.base_url,
    )
    if cfg.provider == "anthropic":
        return _call_anthropic(system_prompt, user_prompt, cfg)
    elif cfg.provider == "ollama":
        return _call_ollama(system_prompt, user_prompt, cfg)
    else:  # openai-compatible (LM Studio, OpenAI, etc.)
        return _call_openai_compatible(system_prompt, user_prompt, cfg)


# ---------------------------------------------------------------------------
# Admin helpers — connection test + model list fetch
# ---------------------------------------------------------------------------


def test_connection(cfg: LlmConfig) -> tuple[bool, str]:
    """Quick connectivity probe.  Returns ``(ok, human_readable_message)``."""
    try:
        t0 = time.monotonic()

        if cfg.provider == "anthropic":
            # Anthropic has no /v1/models endpoint — send a minimal completion
            _call_anthropic("Respond with exactly: ok", "ok", cfg)
            elapsed = time.monotonic() - t0
            return True, f"Connected · {elapsed:.1f}s · {cfg.model}"

        elif cfg.provider == "ollama":
            url = cfg.base_url + "/api/tags"
            resp = httpx.get(url, timeout=10)
            resp.raise_for_status()
            elapsed = time.monotonic() - t0
            names = [m.get("name", "") for m in (resp.json().get("models") or [])]
            note  = f" · model not in tag list" if cfg.model not in names else ""
            return True, f"Connected · {elapsed:.1f}s · {cfg.model}{note}"

        else:  # openai-compatible
            url = cfg.base_url + "/v1/models"
            headers: dict[str, str] = {}
            if cfg.api_key:
                headers["Authorization"] = f"Bearer {cfg.api_key}"
            resp = httpx.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            elapsed   = time.monotonic() - t0
            ids       = [m.get("id", "") for m in (resp.json().get("data") or [])]
            model_txt = cfg.model if cfg.model in ids else f"{cfg.model} (not listed)"
            return True, f"Connected · {elapsed:.1f}s · {model_txt}"

    except httpx.ConnectError:
        return False, (
            f"Connection refused — is the {cfg.provider} server "
            f"running at {cfg.base_url}?"
        )
    except httpx.TimeoutException:
        return False, f"Timeout — {cfg.base_url} did not respond within 10s"
    except Exception as exc:
        return False, f"Error: {exc}"


def fetch_models(cfg: LlmConfig) -> list[str]:
    """Return available model IDs from the configured endpoint."""
    try:
        if cfg.provider == "anthropic":
            return list(config.CLAUDE_MODEL_REGISTRY.keys())
        elif cfg.provider == "ollama":
            url  = cfg.base_url + "/api/tags"
            resp = httpx.get(url, timeout=10)
            resp.raise_for_status()
            return [m.get("name", "") for m in (resp.json().get("models") or []) if m.get("name")]
        else:  # openai-compatible
            url  = cfg.base_url + "/v1/models"
            hdrs: dict[str, str] = {}
            if cfg.api_key:
                hdrs["Authorization"] = f"Bearer {cfg.api_key}"
            resp = httpx.get(url, headers=hdrs, timeout=10)
            resp.raise_for_status()
            return [m.get("id", "") for m in (resp.json().get("data") or []) if m.get("id")]
    except Exception as exc:
        log.warning("fetch_models failed: %s", exc)
        return []
