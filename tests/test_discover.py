"""Discovery tests: source parsers on sample payloads, scoring, storage and the API. No real network."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from jobhunt import discover, jobs, ledger, roles
from jobhunt.db import connect
from jobhunt.discover import Posting, score_posting, strip_html


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBHUNT_HOME", str(tmp_path))
    for var in ("ADZUNA_APP_ID", "ADZUNA_APP_KEY", "RAPIDAPI_KEY"):
        monkeypatch.delenv(var, raising=False)
    c = connect()
    yield c
    c.close()


def serve(routes):
    """routes: {path_prefix: (status, payload)}; records requests."""
    calls = []

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append({"path": self.path, "headers": dict(self.headers)})
            for prefix, (status, payload) in routes.items():
                if self.path.startswith(prefix):
                    break
            else:
                status, payload = 404, {"error": "no route"}
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


REMOTIVE = {"jobs": [{"id": 101, "url": "https://remotive.com/j/101", "title": "Senior Platform Engineer", "company_name": "Acme",
                      "tags": ["kubernetes", "terraform"], "publication_date": "2026-09-15T10:00:00",
                      "candidate_required_location": "Worldwide", "salary": "$150k",
                      "description": "<p>We need <b>Kubernetes</b> and Terraform.<br>Go a plus.</p>"}]}
REMOTEOK = [{"legal": "notice"},
            {"id": "7", "company": "Globex", "position": "Backend Engineer (Python)", "tags": ["python", "postgres"], "location": "Remote",
             "url": "https://remoteok.com/l/7", "date": "2026-09-10T00:00:00+00:00", "description": "Python and PostgreSQL", "salary_min": 90000, "salary_max": 120000},
            {"id": "8", "company": "Other", "position": "Sales Lead", "tags": ["sales"], "url": "https://remoteok.com/l/8", "description": "Sell things"}]
ARBEITNOW = {"data": [{"slug": "dev-1", "title": "Platform Engineer", "company_name": "Initech", "remote": True, "url": "https://arbeitnow.com/j/dev-1",
                       "tags": ["Kubernetes"], "job_types": ["full-time"], "location": "Berlin", "created_at": 1757894400,
                       "description": "Kubernetes and AWS"},
                      {"slug": "office-1", "title": "Platform Engineer", "company_name": "Onsite Co", "remote": False, "url": "https://arbeitnow.com/j/office-1",
                       "tags": [], "job_types": [], "location": "Munich", "created_at": 1757894400, "description": "onsite"}]}
ADZUNA = {"results": [{"id": "az1", "title": "Platform <strong>Engineer</strong>", "company": {"display_name": "Umbrella"},
                       "location": {"display_name": "Bengaluru, Karnataka"}, "description": "Remote friendly. Kubernetes, Terraform, Python.",
                       "redirect_url": "https://adzuna.in/r/az1", "created": "2026-09-12T08:00:00Z", "salary_min": 2500000, "salary_max": 3500000,
                       "category": {"label": "IT Jobs"}}]}
JSEARCH = {"data": [{"job_id": "js1", "job_title": "Platform Engineer", "employer_name": "LinkedIn Listed Co", "job_city": "Bengaluru",
                     "job_state": "Karnataka", "job_country": "IN", "job_is_remote": False, "job_apply_link": "https://www.linkedin.com/jobs/view/1",
                     "job_description": "Kubernetes, Helm and Python.", "job_posted_at_datetime_utc": "2026-09-16T00:00:00.000Z",
                     "job_publisher": "LinkedIn", "job_min_salary": None, "job_max_salary": None, "job_employment_type": "FULLTIME",
                     "job_highlights": {"Qualifications": ["5 years Kubernetes"]}}]}


def test_strip_html_and_salary():
    assert strip_html("<p>Hello <b>world</b><br>next</p>") == "Hello world\nnext"
    assert discover._salary(90000, 120000, "USD") == "USD 90k-120k"
    assert discover._salary(None, None) is None


def test_source_parsers(monkeypatch):
    srv, base, calls = serve({"/remotive": (200, REMOTIVE), "/remoteok": (200, REMOTEOK), "/arbeitnow": (200, ARBEITNOW),
                              "/adzuna": (200, ADZUNA), "/jsearch": (200, JSEARCH)})
    try:
        monkeypatch.setattr(discover.Remotive, "base_url", base + "/remotive")
        monkeypatch.setattr(discover.RemoteOK, "base_url", base + "/remoteok")
        monkeypatch.setattr(discover.Arbeitnow, "base_url", base + "/arbeitnow")
        monkeypatch.setattr(discover.Adzuna, "base_url", base + "/adzuna")
        monkeypatch.setattr(discover.JSearch, "base_url", base + "/jsearch")

        r = discover.Remotive().search("platform engineer", "", False, "in", {})
        assert r[0].remote and r[0].company == "Acme" and "Kubernetes and Terraform" in r[0].description and r[0].posted_at == "2026-09-15T10:00:00"

        ro = discover.RemoteOK().search("python", "", False, "in", {})
        assert [p.title for p in ro] == ["Backend Engineer (Python)"]  # legal notice skipped, sales job filtered out
        assert ro[0].salary == "USD 90k-120k"

        ar = discover.Arbeitnow().search("platform", "", True, "in", {})
        assert [p.company for p in ar] == ["Initech"]  # remote_only drops the onsite one
        assert ar[0].posted_at == "2025-09-15T00:00:00"

        az = discover.Adzuna().search("platform engineer", "Bengaluru", False, "in", {"adzuna_app_id": "id", "adzuna_app_key": "key"})
        assert az[0].title == "Platform Engineer" and az[0].remote is True and az[0].location == "Bengaluru, Karnataka"
        assert "/adzuna/in/search/1" in calls[-1]["path"] and "app_key=key" in calls[-1]["path"]

        js = discover.JSearch().search("platform engineer", "Bengaluru, India", False, "in", {"rapidapi_key": "rk"})
        assert js[0].publisher == "LinkedIn" and js[0].location == "Bengaluru, Karnataka, IN"
        assert js[0].description.startswith("Qualifications:")
        sent = {k.lower(): v for k, v in calls[-1]["headers"].items()}
        assert sent["x-rapidapi-key"] == "rk" and "country=in" in calls[-1]["path"]
    finally:
        srv.shutdown()


def test_scoring_prefers_skill_and_title_matches():
    skills = ["Kubernetes", "Terraform", "Python", "Go", "C++"]
    strong = Posting("x", "1", "Senior Platform Engineer", "u", description="Kubernetes, Terraform and Python. C++ too.", posted_at="2099-01-01T00:00:00")
    weak = Posting("x", "2", "Account Manager", "u", description="Sales and CRM", posted_at=None)
    s1, m1 = score_posting(strong, skills, ["Platform Engineer"])
    s2, m2 = score_posting(weak, skills, ["Platform Engineer"])
    assert set(m1) == {"Kubernetes", "Terraform", "Python", "C++"} and m2 == []
    assert s1 > 70 > s2 == 0
    # "Go" must not match inside "Google"
    _, m3 = score_posting(Posting("x", "3", "Eng", "u", description="Google Cloud only"), ["Go"], [])
    assert m3 == []


def test_run_search_stores_scores_and_survives_bad_source(conn, monkeypatch):
    ledger.add_entry(conn, "skill", "Kubernetes", level="advanced")
    ledger.add_entry(conn, "experience", "SRE", org="X", skills=["Terraform", "Python"])
    rid = roles.add_role(conn, "Platform Engineer")
    srv, base, _ = serve({"/remotive": (200, REMOTIVE), "/arbeitnow": (500, {"error": "boom"})})
    try:
        monkeypatch.setattr(discover.Remotive, "base_url", base + "/remotive")
        monkeypatch.setattr(discover.Arbeitnow, "base_url", base + "/arbeitnow")
        res = discover.run_search(conn, "platform engineer", role_id=rid, sources=["remotive", "arbeitnow", "jsearch"])
        assert res["per_source"]["remotive"] == {"count": 1, "new": 1}
        assert "HTTP 500" in res["per_source"]["arbeitnow"]["error"]
        assert res["per_source"]["jsearch"]["error"] == "API key not configured"

        items = discover.list_discovered(conn)
        assert len(items) == 1 and items[0]["match_score"] >= 50  # 2 skills + title match + recency
        assert set(items[0]["matched_skills"]) == {"Kubernetes", "Terraform"}

        # re-running updates instead of duplicating
        res2 = discover.run_search(conn, "platform engineer", sources=["remotive"])
        assert res2["per_source"]["remotive"] == {"count": 1, "new": 0}
        assert len(discover.list_discovered(conn)) == 1
        assert discover.discover_settings(conn)["last_run"]["total"] == 1
    finally:
        srv.shutdown()

    d = items[0]
    saved = discover.save_to_tracker(conn, d["id"])
    assert saved["status"] == "saved" and saved["saved_job_id"]
    j = jobs.get_job(conn, saved["saved_job_id"])
    assert j["company"] == "Acme" and j["url"] == "https://remotive.com/j/101" and j["role_id"] == rid and "Kubernetes" in j["jd_text"]
    assert discover.save_to_tracker(conn, d["id"])["saved_job_id"] == saved["saved_job_id"]  # idempotent
    assert discover.list_discovered(conn, status="new") == []
    assert discover.set_status(conn, d["id"], "dismissed")["status"] == "dismissed"


def test_settings_and_links(conn):
    info = discover.discover_settings(conn)
    assert {s["id"] for s in info["sources"] if s["enabled"]} == {"remotive", "remoteok", "arbeitnow"}
    assert not next(s for s in info["sources"] if s["id"] == "jsearch")["configured"]

    discover.update_discover_settings(conn, location="Bengaluru, India", country="IN", remote_only=True,
                                      sources_enabled=["jsearch", "remotive"], keys={"rapidapi_key": "rk-12345678"})
    info = discover.discover_settings(conn)
    assert info["location"] == "Bengaluru, India" and info["country"] == "in" and info["remote_only"] is True
    js = next(s for s in info["sources"] if s["id"] == "jsearch")
    assert js["enabled"] and js["configured"] and js["keys"][0]["hint"] == "...5678"
    with pytest.raises(ValueError):
        discover.update_discover_settings(conn, country="India")
    with pytest.raises(ValueError):
        discover.update_discover_settings(conn, sources_enabled=["monster"])

    links = {l["id"]: l["url"] for l in discover.external_links("Platform Engineer", "Bengaluru, India", True)}
    assert "linkedin.com/jobs/search/?keywords=Platform+Engineer" in links["linkedin"] and "f_WT=2" in links["linkedin"]
    assert links["naukri"].startswith("https://www.naukri.com/platform-engineer-jobs") and "wfhType=2" in links["naukri"]
    assert links["indeed"].startswith("https://in.indeed.com/jobs?q=Platform+Engineer")


def test_discover_api(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBHUNT_HOME", str(tmp_path))
    from jobhunt.web.api import app

    client = TestClient(app)
    srv, base, _ = serve({"/remotive": (200, REMOTIVE)})
    try:
        monkeypatch.setattr(discover.Remotive, "base_url", base + "/remotive")
        client.post("/api/ledger", json={"kind": "skill", "title": "Kubernetes", "skills": []})
        rid = client.post("/api/roles", json={"title": "Platform Engineer", "required_skills": [], "nice_to_have": [], "priority": 1}).json()["id"]

        info = client.get("/api/discover").json()
        assert "Platform Engineer" in info["suggested_queries"] and info["counts"]["new"] == 0

        r = client.put("/api/discover/settings", json={"location": "Remote", "sources_enabled": ["remotive"], "keys": {"rapidapi_key": "x"}})
        assert r.status_code == 200 and r.json()["location"] == "Remote"

        r = client.post("/api/discover/run", json={"query": "platform engineer", "role_id": rid})
        assert r.status_code == 202
        import time
        for _ in range(100):
            t = client.get(f"/api/tasks/{r.json()['id']}").json()
            if t["status"] != "running":
                break
            time.sleep(0.05)
        assert t["status"] == "done" and t["result"]["new"] == 1

        found = client.get("/api/discover/jobs").json()
        assert len(found) == 1 and found[0]["matched_skills"] == ["Kubernetes"]
        did = found[0]["id"]
        assert client.get("/api/discover/links?query=platform+engineer&location=India").json()[0]["id"] == "linkedin"

        saved = client.post(f"/api/discover/jobs/{did}/save", json={}).json()
        assert saved["status"] == "saved"
        assert client.get(f"/api/jobs/{saved['saved_job_id']}").json()["title"] == "Senior Platform Engineer"
        assert client.get("/api/discover/jobs").json() == []
        assert len(client.get("/api/discover/jobs?status=saved").json()) == 1
        assert client.post("/api/discover/jobs/999/dismiss").status_code == 404
        assert client.post("/api/discover/run", json={"query": "  "}).status_code == 400
    finally:
        srv.shutdown()
