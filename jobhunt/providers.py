"""Model backends. Every provider returns a validated Pydantic object.

- Anthropic: native SDK with structured outputs (messages.parse).
- OpenAI-compatible (OpenAI, Gemini, Groq, OpenRouter): chat completions with
  response_format json_schema, falling back to json_object and then to plain
  JSON-in-text, always validated against the schema.
"""

from __future__ import annotations

import json
import os
import re
import time

from pydantic import BaseModel, ValidationError

from .settings import ProviderConfig

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AIError(RuntimeError):
    """Anything the user needs to fix or retry (auth, network, refusal, bad output)."""


def _cause_chain(exc: BaseException) -> str:
    parts = []
    cause = exc.__cause__ or exc.__context__
    seen = 0
    while cause is not None and seen < 4:
        text = str(cause).strip()
        parts.append(f"{type(cause).__name__}: {text}" if text else type(cause).__name__)
        cause = cause.__cause__ or cause.__context__
        seen += 1
    return " <- ".join(parts)


def _connection_hint(exc: BaseException, label: str) -> str:
    chain = _cause_chain(exc)
    hint = f"Could not reach the {label} API."
    if chain:
        hint += f" Underlying error: {chain}."
    lowered = chain.lower()
    if "process() takes no keyword arguments" in lowered:
        hint += (
            " This is an outdated Brotli decompression package, not a network problem: "
            "run `pip install -U brotli` and restart."
        )
    elif "certificate" in lowered or "ssl" in lowered:
        hint += " This looks like a TLS/certificate problem, often a corporate proxy or antivirus intercepting HTTPS."
    elif "proxy" in lowered or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY"):
        hint += " A proxy is configured; check HTTPS_PROXY/HTTP_PROXY."
    elif "timed out" in lowered or "timeout" in lowered:
        hint += " The request timed out; the network may be slow or blocked."
    else:
        hint += " Check your internet connection, VPN and firewall."
    return hint


def parse(cfg: ProviderConfig, system_blocks: list[str], user: str, schema: type[BaseModel], effort: str = "high") -> BaseModel:
    if not cfg.api_key:
        raise AIError(f"No API key for {cfg.label}. Add one in Settings or set {_env_names(cfg)}.")
    if cfg.kind == "anthropic":
        return _anthropic_parse(cfg, system_blocks, user, schema, effort)
    return _openai_parse(cfg, system_blocks, user, schema)


def _env_names(cfg: ProviderConfig) -> str:
    from .settings import PROVIDERS

    return " or ".join(PROVIDERS[cfg.provider].env_keys)


# --- Anthropic ---------------------------------------------------------------


def _anthropic_parse(cfg: ProviderConfig, system_blocks: list[str], user: str, schema: type[BaseModel], effort: str):
    import anthropic

    client = anthropic.Anthropic(api_key=cfg.api_key, base_url=cfg.base_url)
    system = [{"type": "text", "text": t} for t in system_blocks]
    if len(system) > 1:
        system[-1]["cache_control"] = {"type": "ephemeral"}
    use_fallbacks = os.environ.get("JOBHUNT_FALLBACKS", "1") != "0" and cfg.model.startswith(("claude-opus-5", "claude-fable"))
    kwargs: dict = dict(
        model=cfg.model,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_format=schema,
        output_config={"effort": effort},
    )
    try:
        if use_fallbacks:
            response = client.beta.messages.parse(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
        else:
            response = client.messages.parse(**kwargs)
    except anthropic.AuthenticationError as e:
        raise AIError("Anthropic rejected the API key. Check it in Settings.") from e
    except anthropic.PermissionDeniedError as e:
        raise AIError(f"Anthropic denied access: {e.message}") from e
    except anthropic.NotFoundError as e:
        raise AIError(f"Model {cfg.model!r} was not found on Anthropic. Pick another model in Settings.") from e
    except anthropic.RateLimitError as e:
        retry = e.response.headers.get("retry-after", "a minute")
        raise AIError(f"Rate limited by Anthropic. Retry after {retry}.") from e
    except anthropic.BadRequestError as e:
        raise AIError(f"Anthropic rejected the request: {e.message}") from e
    except anthropic.APIStatusError as e:
        raise AIError(f"Anthropic API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise AIError(_connection_hint(e, "Anthropic")) from e

    if response.stop_reason == "refusal":
        explanation = getattr(response.stop_details, "explanation", None)
        raise AIError("The model declined this request" + (f" ({explanation})." if explanation else "."))
    if response.stop_reason == "max_tokens":
        raise AIError("The response was cut off. Try a shorter input.")
    if response.parsed_output is None:
        raise AIError("The model returned no structured output. Try again.")
    return response.parsed_output


# --- OpenAI-compatible -------------------------------------------------------


def _openai_client(cfg: ProviderConfig):
    import openai

    headers = {"X-Title": "jobhunt"} if cfg.provider == "openrouter" else None
    return openai.OpenAI(api_key=cfg.api_key, base_url=cfg.base_url, timeout=600, max_retries=2, default_headers=headers)


def _strip_fences(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    if m:
        return m.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start > 0 and end > start:
        return text[start : end + 1]
    return text


def _openai_parse(cfg: ProviderConfig, system_blocks: list[str], user: str, schema: type[BaseModel]):
    import openai

    client = _openai_client(cfg)
    schema_json = schema.model_json_schema()
    system_text = "\n\n".join(system_blocks)
    messages: list[dict] = [{"role": "system", "content": system_text}, {"role": "user", "content": user}]
    schema_prompt = (
        "\n\nRespond with a single JSON object that matches this JSON Schema exactly. "
        "No prose, no code fences.\n" + json.dumps(schema_json)
    )

    def create(**extra):
        try:
            return client.chat.completions.create(model=cfg.model, messages=messages, **extra)
        except openai.AuthenticationError as e:
            raise AIError(f"{cfg.label} rejected the API key. Check it in Settings.") from e
        except openai.PermissionDeniedError as e:
            raise AIError(f"{cfg.label} denied access: {_msg(e)}") from e
        except openai.NotFoundError as e:
            raise AIError(f"Model {cfg.model!r} was not found on {cfg.label}. Pick another model in Settings.") from e
        except openai.RateLimitError as e:
            raise AIError(f"Rate limited by {cfg.label}: {_msg(e)}") from e
        except openai.APIConnectionError as e:
            raise AIError(_connection_hint(e, cfg.label)) from e

    # 1. json_schema response format; 2. json_object + schema in prompt; 3. plain text.
    try:
        resp = create(response_format={"type": "json_schema", "json_schema": {"name": schema.__name__, "schema": schema_json}})
    except openai.BadRequestError:
        messages[0]["content"] = system_text + schema_prompt
        try:
            resp = create(response_format={"type": "json_object"})
        except openai.BadRequestError:
            try:
                resp = create()
            except openai.BadRequestError as e:
                raise AIError(f"{cfg.label} rejected the request: {_msg(e)}") from e
    except openai.APIStatusError as e:
        raise AIError(f"{cfg.label} API error {e.status_code}: {_msg(e)}") from e

    result = _validate(resp, schema, cfg)
    if isinstance(result, BaseModel):
        return result

    # One repair round with the validation error.
    messages[0]["content"] = system_text + schema_prompt
    messages.append({"role": "assistant", "content": _content(resp)})
    messages.append({"role": "user", "content": f"That JSON did not validate: {result}\nReturn a corrected JSON object only."})
    try:
        resp = create(response_format={"type": "json_object"})
    except (openai.BadRequestError, openai.APIStatusError):
        resp = create()
    result = _validate(resp, schema, cfg)
    if isinstance(result, BaseModel):
        return result
    raise AIError(f"{cfg.label} returned output that does not match the expected structure: {result}")


def _msg(e) -> str:
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        err = body.get("error", body)
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
    return str(getattr(e, "message", e))


def _content(resp) -> str:
    try:
        return resp.choices[0].message.content or ""
    except (AttributeError, IndexError):
        return ""


def _validate(resp, schema: type[BaseModel], cfg: ProviderConfig):
    if not getattr(resp, "choices", None):
        raise AIError(f"{cfg.label} returned no choices.")
    choice = resp.choices[0]
    if getattr(choice, "finish_reason", None) == "length":
        raise AIError("The response was cut off. Try a shorter input or a model with a larger output limit.")
    text = _strip_fences(_content(resp))
    if not text:
        raise AIError(f"{cfg.label} returned an empty response.")
    try:
        return schema.model_validate_json(text)
    except ValidationError as e:
        return str(e)[:800]
    except ValueError as e:
        return f"not valid JSON: {e}"


# --- connectivity test -------------------------------------------------------


class _Ping(BaseModel):
    ok: bool
    greeting: str


def test_connection(cfg: ProviderConfig) -> dict:
    """Make the smallest possible structured call and report latency."""
    t0 = time.perf_counter()
    result = parse(cfg, ["You are a connectivity check."], "Reply with ok=true and a one-word greeting.", _Ping, effort="low")
    return {
        "ok": True,
        "provider": cfg.provider,
        "model": cfg.model,
        "latency_ms": round((time.perf_counter() - t0) * 1000),
        "reply": result.greeting,
    }
