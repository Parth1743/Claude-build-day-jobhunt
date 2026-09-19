"""AI provider registry and persisted settings.

Resolution order for every value: database setting, then environment
variable (including .env), then the provider default.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass

from .db import now

DEFAULT_PROVIDER = "anthropic"


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    kind: str  # "anthropic" | "openai" (OpenAI-compatible chat completions)
    env_keys: tuple[str, ...]
    base_url: str | None
    default_model: str
    docs: str
    models_hint: tuple[str, ...]
    env_base_url: str | None = None


PROVIDERS: dict[str, Provider] = {
    "anthropic": Provider(
        id="anthropic",
        label="Anthropic Claude",
        kind="anthropic",
        env_keys=("ANTHROPIC_API_KEY",),
        base_url=None,
        default_model="claude-opus-5",
        docs="https://console.anthropic.com/settings/keys",
        models_hint=("claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"),
        env_base_url="ANTHROPIC_BASE_URL",
    ),
    "openai": Provider(
        id="openai",
        label="OpenAI",
        kind="openai",
        env_keys=("OPENAI_API_KEY",),
        base_url="https://api.openai.com/v1",
        default_model="gpt-4.1",
        docs="https://platform.openai.com/api-keys",
        models_hint=("gpt-4.1", "gpt-4.1-mini", "o4-mini"),
        env_base_url="OPENAI_BASE_URL",
    ),
    "gemini": Provider(
        id="gemini",
        label="Google Gemini",
        kind="openai",
        env_keys=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        default_model="gemini-2.5-flash",
        docs="https://aistudio.google.com/apikey",
        models_hint=("gemini-2.5-pro", "gemini-2.5-flash"),
        env_base_url="GEMINI_BASE_URL",
    ),
    "groq": Provider(
        id="groq",
        label="Groq",
        kind="openai",
        env_keys=("GROQ_API_KEY",),
        base_url="https://api.groq.com/openai/v1",
        default_model="llama-3.3-70b-versatile",
        docs="https://console.groq.com/keys",
        models_hint=("llama-3.3-70b-versatile", "openai/gpt-oss-120b", "moonshotai/kimi-k2-instruct"),
        env_base_url="GROQ_BASE_URL",
    ),
    "openrouter": Provider(
        id="openrouter",
        label="OpenRouter",
        kind="openai",
        env_keys=("OPENROUTER_API_KEY",),
        base_url="https://openrouter.ai/api/v1",
        default_model="anthropic/claude-sonnet-4",
        docs="https://openrouter.ai/settings/keys",
        models_hint=("anthropic/claude-sonnet-4", "openai/gpt-4.1", "google/gemini-2.5-pro"),
        env_base_url="OPENROUTER_BASE_URL",
    ),
}


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    kind: str
    label: str
    model: str
    api_key: str | None
    base_url: str | None
    key_source: str | None  # "saved" | "env" | None


# --- raw settings ------------------------------------------------------------


def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row is not None else default


def set_setting(conn: sqlite3.Connection, key: str, value: str | None) -> None:
    if value is None or value == "":
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))
    else:
        conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, value, now()),
        )
    conn.commit()


# --- resolution --------------------------------------------------------------


def _env_key(p: Provider) -> str | None:
    for name in p.env_keys:
        v = os.environ.get(name)
        if v:
            return v
    return None


def key_for(conn: sqlite3.Connection, provider_id: str) -> tuple[str | None, str | None]:
    """Return (api_key, source) where source is 'saved', 'env' or None."""
    p = PROVIDERS[provider_id]
    saved = get_setting(conn, f"{provider_id}_api_key")
    if saved:
        return saved, "saved"
    env = _env_key(p)
    if env:
        return env, "env"
    return None, None


def current_provider_id(conn: sqlite3.Connection) -> str:
    pid = get_setting(conn, "provider") or os.environ.get("JOBHUNT_PROVIDER") or DEFAULT_PROVIDER
    return pid if pid in PROVIDERS else DEFAULT_PROVIDER


def resolve(conn: sqlite3.Connection) -> ProviderConfig:
    pid = current_provider_id(conn)
    p = PROVIDERS[pid]
    model = get_setting(conn, f"{pid}_model") or os.environ.get("JOBHUNT_MODEL") or p.default_model
    base_url = get_setting(conn, f"{pid}_base_url") or (os.environ.get(p.env_base_url) if p.env_base_url else None) or p.base_url
    key, source = key_for(conn, pid)
    return ProviderConfig(provider=pid, kind=p.kind, label=p.label, model=model, api_key=key, base_url=base_url, key_source=source)


def mask(key: str | None) -> str | None:
    if not key:
        return None
    return f"...{key[-4:]}" if len(key) > 8 else "..."


def describe(conn: sqlite3.Connection) -> dict:
    """Everything the settings page needs, with keys masked."""
    cfg = resolve(conn)
    providers = []
    for p in PROVIDERS.values():
        key, source = key_for(conn, p.id)
        providers.append({
            "id": p.id,
            "label": p.label,
            "kind": p.kind,
            "default_model": p.default_model,
            "model": get_setting(conn, f"{p.id}_model") or "",
            "base_url": get_setting(conn, f"{p.id}_base_url") or "",
            "default_base_url": p.base_url,
            "env_keys": list(p.env_keys),
            "key_status": source,
            "key_hint": mask(key),
            "docs": p.docs,
            "models_hint": list(p.models_hint),
        })
    return {"provider": cfg.provider, "model": cfg.model, "ai_configured": bool(cfg.api_key), "providers": providers}


def update(conn: sqlite3.Connection, *, provider: str | None = None, model: str | None = None,
           base_url: str | None = None, api_keys: dict[str, str] | None = None,
           model_provider: str | None = None) -> None:
    """Apply a partial settings update. Empty strings clear the value.

    `model` and `base_url` apply to `model_provider` if given, else to the
    (possibly just-changed) current provider.
    """
    if provider is not None:
        if provider not in PROVIDERS:
            raise ValueError(f"unknown provider {provider!r}; choose one of {', '.join(PROVIDERS)}")
        set_setting(conn, "provider", provider)
    target = model_provider or current_provider_id(conn)
    if target not in PROVIDERS:
        raise ValueError(f"unknown provider {target!r}")
    if model is not None:
        set_setting(conn, f"{target}_model", model.strip())
    if base_url is not None:
        set_setting(conn, f"{target}_base_url", base_url.strip())
    for pid, key in (api_keys or {}).items():
        if pid not in PROVIDERS:
            raise ValueError(f"unknown provider {pid!r}")
        if key is None:
            continue
        set_setting(conn, f"{pid}_api_key", key.strip())
