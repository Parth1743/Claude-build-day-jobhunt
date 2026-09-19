import os
import pytest

from jobhunt import jobs, ledger, roles
from jobhunt.db import connect


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBHUNT_HOME", str(tmp_path))
    c = connect()
    yield c
    c.close()


def test_ledger_add_update_retire_keeps_history(conn):
    eid = ledger.add_entry(
        conn, "experience", "Backend Engineer", org="Acme", start_date="2022-01",
        description="Built APIs", skills=["Python", "python", "PostgreSQL"],
    )
    e = ledger.get_entry(conn, eid)
    assert e["skills"] == ["Python", "PostgreSQL"]  # de-duplicated case-insensitively

    ledger.update_entry(conn, eid, end_date="2024-06", skills=["Python", "Go"])
    e = ledger.get_entry(conn, eid)
    assert e["end_date"] == "2024-06"
    assert e["skills"] == ["Python", "Go"]

    ledger.retire_entry(conn, eid)
    assert ledger.list_entries(conn) == []
    assert len(ledger.list_entries(conn, include_inactive=True)) == 1

    actions = [h["action"] for h in ledger.history(conn, eid)]
    assert actions == ["retire", "update", "create"]


def test_ledger_validates_kind_and_level(conn):
    with pytest.raises(ValueError):
        ledger.add_entry(conn, "hobby", "Chess")
    with pytest.raises(ValueError):
        ledger.add_entry(conn, "skill", "Rust", level="ninja")
    with pytest.raises(KeyError):
        ledger.update_entry(conn, 999, title="x")


def test_skill_map_merges_levels_and_evidence(conn):
    ledger.add_entry(conn, "skill", "Python", level="advanced")
    ledger.add_entry(conn, "experience", "Data Engineer", org="Corp", skills=["Python", "Spark"])
    ledger.add_entry(conn, "project", "ETL pipeline", skills=["python"])
    sm = ledger.skill_map(conn)
    assert sm["python"]["level"] == "advanced"
    assert sm["python"]["evidence"] == ["Data Engineer @ Corp", "ETL pipeline"]
    assert sm["spark"]["level"] is None


def test_profile_markdown_renders_sections(conn):
    assert "(ledger is empty)" in ledger.profile_markdown(conn)
    ledger.add_entry(conn, "experience", "SWE", org="X", start_date="2021", description="Did things", skills=["Go"])
    ledger.add_entry(conn, "certification", "AWS SAA", org="Amazon", end_date="2023-05")
    md = ledger.profile_markdown(conn)
    assert "## Experience" in md and "**SWE** - X (2021 to present)" in md
    assert "## Certifications" in md and "AWS SAA" in md
    assert "## Skills" in md and "- Go" in md


def test_job_pipeline_and_funnel(conn):
    rid = roles.add_role(conn, "Backend Engineer", required_skills=["Go", "SQL"])
    jid = jobs.add_job(conn, "Acme", "Backend Dev", role_id=rid, jd_text="Need Go and SQL")
    assert jobs.get_job(conn, jid)["status"] == "saved"
    assert jobs.get_job(conn, jid)["role_title"] == "Backend Engineer"

    jobs.set_status(conn, jid, "applied", note="via portal")
    j = jobs.get_job(conn, jid)
    assert j["status"] == "applied" and j["applied_at"] is not None

    jobs.set_status(conn, jid, "interview")
    assert jobs.get_job(conn, jid)["applied_at"] == j["applied_at"]  # applied_at is sticky
    assert [h["to_status"] for h in jobs.job_history(conn, jid)] == ["saved", "applied", "interview"]

    with pytest.raises(ValueError):
        jobs.set_status(conn, jid, "ghosted")

    jobs.add_note(conn, jid, "recruiter call went well")
    assert "recruiter call" in jobs.get_job(conn, jid)["notes"]

    jobs.save_analysis(conn, jid, {"fit_summary": "ok", "matched_skills": ["Go"], "missing_skills": ["SQL"]}, 70)
    j = jobs.get_job(conn, jid)
    assert j["fit_score"] == 70 and j["analysis"]["missing_skills"] == ["SQL"]

    f = jobs.funnel(conn)
    assert f["interview"] == 1 and f["saved"] == 0


def test_roles_lookup_by_id_or_title(conn):
    rid = roles.add_role(conn, "ML Engineer", required_skills=["PyTorch"])
    assert roles.get_role(conn, str(rid))["title"] == "ML Engineer"
    assert roles.get_role(conn, "ml engineer")["id"] == rid
    with pytest.raises(KeyError):
        roles.get_role(conn, "Astronaut")


def test_roadmap_replace_keeps_done_items(conn):
    rid = roles.add_role(conn, "Platform Engineer")
    ids = roles.replace_roadmap(conn, rid, [
        {"skill": "Kubernetes", "priority": 1, "why": "core", "actions": ["a"], "resources": [], "est_weeks": 3},
        {"skill": "Terraform", "priority": 2, "why": "iac", "actions": ["b"], "resources": [], "est_weeks": 2},
    ])
    roles.set_item_status(conn, ids[0], "done")
    roles.replace_roadmap(conn, rid, [
        {"skill": "Helm", "priority": 1, "why": "pkg", "actions": [], "resources": [], "est_weeks": 1},
    ])
    open_items = roles.list_roadmap(conn, rid)
    assert [i["skill"] for i in open_items] == ["Helm"]
    all_items = roles.list_roadmap(conn, rid, include_closed=True)
    assert {i["skill"] for i in all_items} == {"Helm", "Kubernetes"}
    assert all_items[-1]["status"] == "done"


def test_connection_usable_across_threads(tmp_path, monkeypatch):
    """FastAPI opens the connection in one worker thread and uses it in another."""
    import threading

    monkeypatch.setenv("JOBHUNT_HOME", str(tmp_path))
    c = connect()
    errors = []

    def use():
        try:
            ledger.add_entry(c, "skill", "Threading")
            assert ledger.list_entries(c)[0]["title"] == "Threading"
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    t = threading.Thread(target=use)
    t.start()
    t.join()
    c.close()
    assert errors == []


def test_concurrent_writers_do_not_lock(tmp_path, monkeypatch):
    import threading

    monkeypatch.setenv("JOBHUNT_HOME", str(tmp_path))
    errors = []

    def writer(n):
        try:
            c = connect()
            for i in range(10):
                jobs.add_job(c, f"Co{n}", f"Role {i}")
            c.close()
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    c = connect()
    assert len(jobs.list_jobs(c)) == 50
    c.close()


def test_dotenv_loading(tmp_path, monkeypatch):
    from jobhunt import config

    monkeypatch.delenv("JOBHUNT_TEST_VAR", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text('JOBHUNT_TEST_VAR="hello"\nsk-ant-bare-key-line\n', encoding="utf-8")
    config.load_dotenv()
    assert os.environ["JOBHUNT_TEST_VAR"] == "hello"
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-bare-key-line"
    monkeypatch.delenv("JOBHUNT_TEST_VAR")
    monkeypatch.delenv("ANTHROPIC_API_KEY")
