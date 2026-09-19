"""Provider layer tests against fake HTTP servers. No real network calls."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from pydantic import BaseModel

from jobhunt import providers, settings
from jobhunt.db import connect
from jobhunt.providers import AIError


class Pet(BaseModel):
    name: str
    legs: int


def fake_server(handler_fn):
    """Spin up a local HTTP server whose POST handler is handler_fn(body: dict, path) -> (status, body dict)."""
    calls = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("content-length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            calls.append({"path": self.path, "body": body, "headers": dict(self.headers)})
            status, payload = handler_fn(body, self.path)
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}", calls


def chat_reply(text, finish="stop"):
    return {
        "id": "x", "object": "chat.completion", "created": 0, "model": "m",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": finish}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def cfg_for(base, provider="groq", model="test-model", key="k"):
    return settings.ProviderConfig(provider=provider, kind="openai", label=provider, model=model, api_key=key, base_url=base, key_source="saved")


def test_openai_compat_json_schema_path():
    srv, base, calls = fake_server(lambda body, path: (200, chat_reply('{"name": "Rex", "legs": 4}')))
    try:
        pet = providers.parse(cfg_for(base), ["sys"], "user", Pet)
        assert pet == Pet(name="Rex", legs=4)
        assert calls[0]["path"].endswith("/chat/completions")
        assert calls[0]["body"]["response_format"]["type"] == "json_schema"
        assert calls[0]["body"]["model"] == "test-model"
        assert calls[0]["headers"].get("Authorization") == "Bearer k"
    finally:
        srv.shutdown()


def test_openai_compat_falls_back_to_json_object_and_strips_fences():
    def handler(body, path):
        fmt = body.get("response_format", {}).get("type")
        if fmt == "json_schema":
            return 400, {"error": {"message": "response_format json_schema not supported", "type": "invalid_request_error"}}
        return 200, chat_reply('```json\n{"name": "Tom", "legs": 4}\n```')

    srv, base, calls = fake_server(handler)
    try:
        pet = providers.parse(cfg_for(base), ["sys"], "user", Pet)
        assert pet.name == "Tom"
        assert [c["body"]["response_format"]["type"] for c in calls] == ["json_schema", "json_object"]
        assert "JSON Schema" in calls[1]["body"]["messages"][0]["content"]
    finally:
        srv.shutdown()


def test_openai_compat_repairs_invalid_output_once():
    replies = iter(['{"name": "Bad", "legs": "four"}', '{"name": "Good", "legs": 4}'])
    srv, base, calls = fake_server(lambda body, path: (200, chat_reply(next(replies))))
    try:
        pet = providers.parse(cfg_for(base), ["sys"], "user", Pet)
        assert pet.legs == 4
        assert len(calls) == 2
        assert "did not validate" in calls[1]["body"]["messages"][-1]["content"]
    finally:
        srv.shutdown()


def test_openai_compat_auth_and_model_errors_are_friendly():
    srv, base, _ = fake_server(lambda body, path: (401, {"error": {"message": "bad key"}}))
    try:
        with pytest.raises(AIError, match="rejected the API key"):
            providers.parse(cfg_for(base), ["sys"], "user", Pet)
    finally:
        srv.shutdown()
    srv, base, _ = fake_server(lambda body, path: (404, {"error": {"message": "no such model"}}))
    try:
        with pytest.raises(AIError, match="was not found"):
            providers.parse(cfg_for(base), ["sys"], "user", Pet)
    finally:
        srv.shutdown()


def test_missing_key_is_explained():
    cfg = settings.ProviderConfig(provider="openai", kind="openai", label="OpenAI", model="m", api_key=None, base_url=None, key_source=None)
    with pytest.raises(AIError, match="OPENAI_API_KEY"):
        providers.parse(cfg, ["sys"], "user", Pet)


def test_connection_error_includes_cause():
    cfg = cfg_for("http://127.0.0.1:9", key="k")  # nothing listens here
    with pytest.raises(AIError) as exc:
        providers.parse(cfg, ["sys"], "user", Pet)
    assert "Could not reach" in str(exc.value) and "Underlying error" in str(exc.value)


def test_anthropic_path_uses_structured_outputs():
    def handler(body, path):
        assert "/v1/messages" in path  # beta endpoint appends ?beta=true
        payload = {"name": "Ada", "legs": 2}
        return 200, {
            "id": "msg", "type": "message", "role": "assistant", "model": body["model"],
            "content": [{"type": "text", "text": json.dumps(payload)}],
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    srv, base, calls = fake_server(handler)
    try:
        cfg = settings.ProviderConfig(provider="anthropic", kind="anthropic", label="Anthropic", model="claude-opus-5", api_key="sk-ant-test", base_url=base, key_source="saved")
        pet = providers.parse(cfg, ["instructions", "ledger"], "user", Pet)
        assert pet.name == "Ada"
        body = calls[0]["body"]
        assert body["output_config"]["format"]["type"] == "json_schema"
        assert body["system"][-1]["cache_control"] == {"type": "ephemeral"}
        assert body["fallbacks"] == "default"
    finally:
        srv.shutdown()


def test_settings_resolution_and_masking(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBHUNT_HOME", str(tmp_path))
    for var in ("ANTHROPIC_API_KEY", "GROQ_API_KEY", "JOBHUNT_PROVIDER", "JOBHUNT_MODEL"):
        monkeypatch.delenv(var, raising=False)
    conn = connect()
    cfg = settings.resolve(conn)
    assert cfg.provider == "anthropic" and cfg.api_key is None and cfg.model == "claude-opus-5"

    monkeypatch.setenv("GROQ_API_KEY", "gsk_environment_key_1234")
    settings.update(conn, provider="groq", model="llama-3.3-70b-versatile")
    cfg = settings.resolve(conn)
    assert cfg.provider == "groq" and cfg.key_source == "env" and cfg.base_url == "https://api.groq.com/openai/v1"

    settings.update(conn, api_keys={"groq": "gsk_saved_key_5678"})
    cfg = settings.resolve(conn)
    assert cfg.api_key == "gsk_saved_key_5678" and cfg.key_source == "saved"  # saved wins over env

    info = settings.describe(conn)
    groq = next(p for p in info["providers"] if p["id"] == "groq")
    assert groq["key_hint"] == "...5678" and "gsk_saved" not in json.dumps(info)

    settings.update(conn, api_keys={"groq": ""})
    assert settings.resolve(conn).key_source == "env"

    with pytest.raises(ValueError):
        settings.update(conn, provider="bedrock")
    conn.close()
