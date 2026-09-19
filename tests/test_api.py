import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBHUNT_HOME", str(tmp_path))
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
                "GROQ_API_KEY", "OPENROUTER_API_KEY", "JOBHUNT_PROVIDER", "JOBHUNT_MODEL"):
        monkeypatch.delenv(var, raising=False)
    from jobhunt.web.api import app

    return TestClient(app)


def test_config_and_empty_dashboard(client):
    cfg = client.get("/api/config").json()
    assert cfg["ai_configured"] is False and cfg["provider"] == "anthropic"
    assert "experience" in cfg["ledger_kinds"]
    dash = client.get("/api/status").json()
    assert dash["skill_count"] == 0 and dash["funnel"]["saved"] == 0


def test_ledger_crud_and_history(client):
    r = client.post("/api/ledger", json={"kind": "experience", "title": "SWE", "org": "Acme", "skills": ["Python", "Go"]})
    assert r.status_code == 201
    eid = r.json()["id"]

    r = client.patch(f"/api/ledger/{eid}", json={"end_date": "2024-01", "skills": ["Python"]})
    assert r.json()["skills"] == ["Python"] and r.json()["end_date"] == "2024-01"

    assert client.get("/api/ledger/skills").json()[0]["name"] == "Python"
    assert len(client.get(f"/api/ledger/{eid}/history").json()) == 2

    r = client.delete(f"/api/ledger/{eid}")
    assert r.json()["active"] == 0
    assert client.get("/api/ledger").json() == []
    assert len(client.get("/api/ledger?include_inactive=true").json()) == 1

    assert client.get("/api/ledger/999").status_code == 404
    assert client.post("/api/ledger", json={"kind": "hobby", "title": "x", "skills": []}).status_code == 400
    assert "# Profile" in client.get("/api/ledger/export").text


def test_roles_coverage_and_roadmap(client):
    client.post("/api/ledger", json={"kind": "skill", "title": "Python", "level": "advanced", "skills": []})
    r = client.post("/api/roles", json={"title": "Backend", "required_skills": ["Python", "Kafka"], "nice_to_have": ["Go"], "priority": 1})
    assert r.status_code == 201
    role = r.json()
    cov = {c["skill"]: c["have"] for c in role["coverage"]["required"]}
    assert cov == {"Python": True, "Kafka": False}

    assert client.post("/api/roles", json={"title": "Backend", "required_skills": [], "nice_to_have": [], "priority": 1}).status_code == 409

    r = client.patch(f"/api/roles/{role['id']}", json={"required_skills": ["Python"]})
    assert r.json()["required_skills"] == ["Python"]

    assert client.get(f"/api/roles/{role['id']}/roadmap").json() == []
    r = client.post(f"/api/roles/{role['id']}/roadmap/generate", json={"hours": 5, "weeks": 8})
    assert r.status_code == 503  # no AI key configured


def test_jobs_flow(client):
    role_id = client.post("/api/roles", json={"title": "Data", "required_skills": [], "nice_to_have": [], "priority": 1}).json()["id"]
    r = client.post("/api/jobs", json={"company": "Acme", "title": "Data Eng", "role_id": role_id, "jd_text": "Spark and SQL"})
    assert r.status_code == 201
    job = r.json()
    assert job["status"] == "saved" and job["role_title"] == "Data" and job["history"][0]["to_status"] == "saved"

    r = client.post(f"/api/jobs/{job['id']}/status", json={"status": "applied", "note": "portal"})
    assert r.json()["status"] == "applied" and r.json()["applied_at"]
    assert client.post(f"/api/jobs/{job['id']}/status", json={"status": "ghosted"}).status_code == 400

    r = client.post(f"/api/jobs/{job['id']}/notes", json={"text": "call Friday"})
    assert "call Friday" in r.json()["notes"]

    r = client.patch(f"/api/jobs/{job['id']}", json={"jd_text": "Updated JD", "location": "Remote", "role_id": None})
    assert r.json()["jd_text"] == "Updated JD" and r.json()["location"] == "Remote" and r.json()["role_id"] is None

    assert client.get("/api/jobs/funnel").json()["applied"] == 1
    assert len(client.get("/api/jobs?status=applied").json()) == 1
    assert client.get("/api/jobs/999").status_code == 404
    assert client.post(f"/api/jobs/{job['id']}/analyze").status_code == 503


def test_task_not_found(client):
    assert client.get("/api/tasks/nope").status_code == 404


def test_settings_endpoints(client):
    info = client.get("/api/settings").json()
    assert info["provider"] == "anthropic" and info["ai_configured"] is False
    assert {p["id"] for p in info["providers"]} == {"anthropic", "openai", "gemini", "groq", "openrouter"}

    r = client.put("/api/settings", json={"provider": "openrouter", "model": "openai/gpt-4.1", "api_keys": {"openrouter": "sk-or-secret-9999"}})
    assert r.status_code == 200
    info = r.json()
    assert info["provider"] == "openrouter" and info["model"] == "openai/gpt-4.1" and info["ai_configured"] is True
    orp = next(p for p in info["providers"] if p["id"] == "openrouter")
    assert orp["key_status"] == "saved" and orp["key_hint"] == "...9999"
    assert "sk-or-secret" not in r.text

    cfg = client.get("/api/config").json()
    assert cfg["provider"] == "openrouter" and cfg["ai_configured"] is True

    assert client.put("/api/settings", json={"provider": "nope"}).status_code == 400

    # AI routes now pass the key check; the task itself will fail (unreachable base URL) rather than 503.
    client.put("/api/settings", json={"model_provider": "openrouter", "base_url": "http://127.0.0.1:9"})
    r = client.post("/api/settings/test")
    assert r.status_code == 202
    import time
    for _ in range(100):
        t = client.get(f"/api/tasks/{r.json()['id']}").json()
        if t["status"] != "running":
            break
        time.sleep(0.1)
    assert t["status"] == "error" and "Could not reach" in t["error"]
