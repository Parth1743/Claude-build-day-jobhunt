"""FastAPI application: JSON API under /api plus the built React frontend."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import config, discover, jobs, ledger, roles, services, settings
from ..db import JOB_STATUSES, LEDGER_KINDS, ROADMAP_STATUSES, SKILL_LEVELS, pool
from ..resume_text import read_resume
from . import tasks

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="jobhunt", version="0.2.0", docs_url="/api/docs", openapi_url="/api/openapi.json")


# --- plumbing ----------------------------------------------------------------


def db():
    conn = pool.acquire()
    try:
        yield conn
    finally:
        pool.release(conn)


@app.exception_handler(KeyError)
async def _key_error(_, exc: KeyError):
    return JSONResponse(status_code=404, content={"detail": str(exc.args[0]) if exc.args else "not found"})


@app.exception_handler(ValueError)
async def _value_error(_, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(sqlite3.IntegrityError)
async def _integrity_error(_, exc: sqlite3.IntegrityError):
    return JSONResponse(status_code=409, content={"detail": f"conflict: {exc}"})


def _require_ai(conn):
    try:
        services.ai_config(conn)
    except services.ServiceError as e:
        raise HTTPException(status_code=503, detail=str(e))


def _in_task(kind: str, fn):
    """Run fn(conn) in a background thread with a fresh connection."""

    def wrapped():
        conn = pool.acquire()
        try:
            return fn(conn)
        finally:
            pool.release(conn)

    return tasks.start(kind, wrapped).to_dict()


# --- meta --------------------------------------------------------------------


@app.get("/api/config")
def get_config(conn=Depends(db)):
    cfg = settings.resolve(conn)
    return {
        "ai_configured": bool(cfg.api_key),
        "provider": cfg.provider,
        "provider_label": cfg.label,
        "model": cfg.model,
        "db_path": str(config.db_path()),
        "out_dir": str(config.out_dir()),
        "ledger_kinds": LEDGER_KINDS,
        "skill_levels": SKILL_LEVELS,
        "job_statuses": JOB_STATUSES,
        "roadmap_statuses": ROADMAP_STATUSES,
    }


@app.get("/api/status")
def get_status(conn=Depends(db)):
    entries = ledger.list_entries(conn)
    counts = {k: sum(1 for e in entries if e["kind"] == k) for k in LEDGER_KINDS}
    skills = ledger.skill_map(conn)
    role_rows = []
    for r in roles.list_roles(conn):
        items = roles.list_roadmap(conn, r["id"], include_closed=True)
        have = {k for k in skills}
        req = r["required_skills"]
        role_rows.append({
            "id": r["id"],
            "title": r["title"],
            "priority": r["priority"],
            "required": len(req),
            "covered": sum(1 for s in req if s.lower() in have),
            "open_items": sum(1 for i in items if i["status"] in ("todo", "in_progress")),
            "done_items": sum(1 for i in items if i["status"] == "done"),
        })
    recent_jobs = jobs.list_jobs(conn)[:6]
    recent_changes = ledger.history(conn, None, 8)
    return {
        "ledger_counts": counts,
        "skill_count": len(skills),
        "funnel": jobs.funnel(conn),
        "roles": role_rows,
        "recent_jobs": recent_jobs,
        "recent_changes": [
            {"at": h["at"], "action": h["action"], "source": h["source"], "entry_id": h["entry_id"],
             "title": h["snapshot"].get("title"), "kind": h["snapshot"].get("kind")}
            for h in recent_changes
        ],
    }


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str):
    t = tasks.get(task_id)
    if t is None:
        raise HTTPException(404, "task not found")
    return t.to_dict()


# --- settings ----------------------------------------------------------------


class SettingsIn(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None
    model_provider: Optional[str] = Field(default=None, description="Which provider model/base_url apply to")
    api_keys: dict[str, str] = Field(default_factory=dict, description="provider id -> key; empty string clears")


@app.get("/api/settings")
def settings_get(conn=Depends(db)):
    return settings.describe(conn)


@app.put("/api/settings")
def settings_put(body: SettingsIn, conn=Depends(db)):
    settings.update(
        conn, provider=body.provider, model=body.model, base_url=body.base_url,
        model_provider=body.model_provider, api_keys=body.api_keys,
    )
    return settings.describe(conn)


@app.post("/api/settings/test", status_code=202)
def settings_test(body: Optional[SettingsIn] = None, conn=Depends(db)):
    """Run a tiny structured call on the current provider (or on the provider named in the body)."""
    if body is not None and body.provider:
        settings.update(conn, provider=body.provider)
    _require_ai(conn)
    return _in_task("settings_test", lambda c: services.test_ai(c))


# --- discovery ---------------------------------------------------------------


class DiscoverSettingsIn(BaseModel):
    location: Optional[str] = None
    country: Optional[str] = None
    remote_only: Optional[bool] = None
    sources_enabled: Optional[list[str]] = None
    keys: dict[str, str] = Field(default_factory=dict, description="setting name -> value; empty string clears")


class DiscoverRunIn(BaseModel):
    query: str
    location: Optional[str] = None
    remote_only: Optional[bool] = None
    country: Optional[str] = None
    role_id: Optional[int] = None
    sources: Optional[list[str]] = None


class SaveIn(BaseModel):
    role_id: Optional[int] = None


@app.get("/api/discover")
def discover_get(conn=Depends(db)):
    info = discover.discover_settings(conn)
    info["suggested_queries"] = discover.suggested_queries(conn)
    return info


@app.put("/api/discover/settings")
def discover_settings_put(body: DiscoverSettingsIn, conn=Depends(db)):
    discover.update_discover_settings(
        conn, location=body.location, country=body.country, remote_only=body.remote_only,
        sources_enabled=body.sources_enabled, keys=body.keys,
    )
    return discover.discover_settings(conn)


@app.post("/api/discover/run", status_code=202)
def discover_run(body: DiscoverRunIn, conn=Depends(db)):
    if not body.query.strip():
        raise HTTPException(400, "Enter a search query, for example a target role title.")
    if body.role_id is not None:
        roles.get_role(conn, body.role_id)
    return _in_task(
        "discover_run",
        lambda c: discover.run_search(
            c, body.query, location=body.location, remote_only=body.remote_only,
            country=body.country, role_id=body.role_id, sources=body.sources,
        ),
    )


@app.get("/api/discover/links")
def discover_links(query: str, location: str = "", remote_only: bool = False):
    return discover.external_links(query, location, remote_only)


@app.get("/api/discover/jobs")
def discover_jobs(status: Optional[str] = "new", source: Optional[str] = None, min_score: int = 0,
                  q: Optional[str] = None, remote_only: bool = False, limit: int = 200, conn=Depends(db)):
    return discover.list_discovered(conn, status=status or None, source=source, min_score=min_score, q=q,
                                    remote_only=remote_only, limit=limit)


@app.get("/api/discover/jobs/{did}")
def discover_job(did: int, conn=Depends(db)):
    return discover.get_discovered(conn, did)


@app.post("/api/discover/jobs/{did}/save")
def discover_save(did: int, body: Optional[SaveIn] = None, conn=Depends(db)):
    return discover.save_to_tracker(conn, did, role_id=body.role_id if body else None)


@app.post("/api/discover/jobs/{did}/dismiss")
def discover_dismiss(did: int, conn=Depends(db)):
    return discover.set_status(conn, did, "dismissed")


@app.post("/api/discover/jobs/{did}/restore")
def discover_restore(did: int, conn=Depends(db)):
    return discover.set_status(conn, did, "new")


# --- ledger ------------------------------------------------------------------


class LedgerIn(BaseModel):
    kind: str
    title: str
    org: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    description: Optional[str] = None
    skills: list[str] = Field(default_factory=list)
    level: Optional[str] = None
    url: Optional[str] = None


class LedgerPatch(BaseModel):
    kind: Optional[str] = None
    title: Optional[str] = None
    org: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    description: Optional[str] = None
    skills: Optional[list[str]] = None
    level: Optional[str] = None
    url: Optional[str] = None


@app.get("/api/ledger")
def ledger_list(kind: Optional[str] = None, include_inactive: bool = False, conn=Depends(db)):
    return ledger.list_entries(conn, kind=kind, include_inactive=include_inactive)


@app.post("/api/ledger", status_code=201)
def ledger_create(body: LedgerIn, conn=Depends(db)):
    eid = ledger.add_entry(
        conn, body.kind, body.title, org=body.org, start_date=body.start_date, end_date=body.end_date,
        description=body.description, skills=body.skills, level=body.level, url=body.url, source="web",
    )
    return ledger.get_entry(conn, eid)


@app.get("/api/ledger/skills")
def ledger_skills(conn=Depends(db)):
    return list(ledger.skill_map(conn).values())


@app.get("/api/ledger/history")
def ledger_history_all(limit: int = 50, conn=Depends(db)):
    return ledger.history(conn, None, limit)


@app.get("/api/ledger/export", response_class=PlainTextResponse)
def ledger_export(conn=Depends(db)):
    return ledger.profile_markdown(conn)


@app.get("/api/ledger/{entry_id}")
def ledger_get(entry_id: int, conn=Depends(db)):
    return ledger.get_entry(conn, entry_id)


@app.patch("/api/ledger/{entry_id}")
def ledger_update(entry_id: int, body: LedgerPatch, conn=Depends(db)):
    ledger.update_entry(conn, entry_id, source="web", **body.model_dump(exclude_none=True))
    return ledger.get_entry(conn, entry_id)


@app.delete("/api/ledger/{entry_id}")
def ledger_retire(entry_id: int, conn=Depends(db)):
    ledger.retire_entry(conn, entry_id, source="web")
    return ledger.get_entry(conn, entry_id)


@app.get("/api/ledger/{entry_id}/history")
def ledger_history_one(entry_id: int, conn=Depends(db)):
    ledger.get_entry(conn, entry_id)
    return ledger.history(conn, entry_id)


@app.post("/api/ledger/import", status_code=202)
async def ledger_import(file: UploadFile = File(...), conn=Depends(db)):
    """Upload a resume; returns a task whose result is {entries, notes, source}."""
    _require_ai(conn)
    suffix = Path(file.filename or "resume.txt").suffix or ".txt"
    data = await file.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    try:
        text = read_resume(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)
    source = f"import:{file.filename}"

    def run(c):
        result = services.extract_resume_entries(c, text)
        result["source"] = source
        return result

    return _in_task("ledger_import", run)


class CommitIn(BaseModel):
    entries: list[LedgerIn]
    source: str = "import"


@app.post("/api/ledger/import/commit")
def ledger_import_commit(body: CommitIn, conn=Depends(db)):
    saved, skipped = services.commit_entries(conn, [e.model_dump() for e in body.entries], body.source)
    return {"saved": saved, "skipped": skipped}


# --- roles -------------------------------------------------------------------


class RoleIn(BaseModel):
    title: str
    description: Optional[str] = None
    required_skills: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)
    priority: int = 1


class RolePatch(BaseModel):
    description: Optional[str] = None
    required_skills: Optional[list[str]] = None
    nice_to_have: Optional[list[str]] = None
    priority: Optional[int] = None


class SuggestIn(BaseModel):
    title: str
    hint: Optional[str] = None


def _role_view(conn, r: dict) -> dict:
    have = {k for k in ledger.skill_map(conn)}
    r = dict(r)
    r["coverage"] = {
        "required": [{"skill": s, "have": s.lower() in have} for s in r["required_skills"]],
        "nice_to_have": [{"skill": s, "have": s.lower() in have} for s in r["nice_to_have"]],
    }
    r["job_count"] = sum(1 for j in jobs.list_jobs(conn) if j["role_id"] == r["id"])
    return r


@app.get("/api/roles")
def roles_list(conn=Depends(db)):
    return [_role_view(conn, r) for r in roles.list_roles(conn)]


@app.post("/api/roles", status_code=201)
def roles_create(body: RoleIn, conn=Depends(db)):
    rid = roles.add_role(
        conn, body.title, description=body.description, required_skills=body.required_skills,
        nice_to_have=body.nice_to_have, priority=body.priority,
    )
    return _role_view(conn, roles.get_role(conn, rid))


@app.post("/api/roles/suggest", status_code=202)
def roles_suggest(body: SuggestIn, conn=Depends(db)):
    _require_ai(conn)
    return _in_task("role_suggest", lambda c: services.suggest_role_skills(c, body.title, body.hint))


@app.get("/api/roles/{role_id}")
def roles_get(role_id: int, conn=Depends(db)):
    return _role_view(conn, roles.get_role(conn, role_id))


@app.patch("/api/roles/{role_id}")
def roles_update(role_id: int, body: RolePatch, conn=Depends(db)):
    roles.get_role(conn, role_id)
    roles.update_role(conn, role_id, **body.model_dump(exclude_none=True))
    return _role_view(conn, roles.get_role(conn, role_id))


# --- roadmap -----------------------------------------------------------------


class GenerateIn(BaseModel):
    hours: int = 8
    weeks: int = 12
    include_jobs: bool = True


class ItemStatusIn(BaseModel):
    status: str
    level: Optional[str] = "intermediate"
    proof: Optional[str] = None
    add_to_ledger: bool = True


@app.get("/api/roles/{role_id}/roadmap")
def roadmap_list(role_id: int, include_closed: bool = True, conn=Depends(db)):
    roles.get_role(conn, role_id)
    return roles.list_roadmap(conn, role_id, include_closed=include_closed)


@app.post("/api/roles/{role_id}/roadmap/generate", status_code=202)
def roadmap_generate(role_id: int, body: GenerateIn, conn=Depends(db)):
    _require_ai(conn)
    role = roles.get_role(conn, role_id)
    return _in_task(
        "roadmap_generate",
        lambda c: services.generate_roadmap(c, role, body.hours, body.weeks, body.include_jobs),
    )


@app.get("/api/roadmap/{item_id}")
def roadmap_item(item_id: int, conn=Depends(db)):
    return roles.get_item(conn, item_id)


@app.post("/api/roadmap/{item_id}/status")
def roadmap_item_status(item_id: int, body: ItemStatusIn, conn=Depends(db)):
    if body.status == "done":
        eid = services.complete_roadmap_item(
            conn, item_id, level=body.level, proof=body.proof, add_to_ledger=body.add_to_ledger
        )
        item = roles.get_item(conn, item_id)
        item["ledger_entry_id"] = eid
        return item
    roles.set_item_status(conn, item_id, body.status)
    return roles.get_item(conn, item_id)


# --- jobs --------------------------------------------------------------------


class JobIn(BaseModel):
    company: str
    title: str
    url: Optional[str] = None
    location: Optional[str] = None
    role_id: Optional[int] = None
    jd_text: Optional[str] = None
    notes: Optional[str] = None


class JobPatch(BaseModel):
    company: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None
    location: Optional[str] = None
    role_id: Optional[int] = None
    jd_text: Optional[str] = None


class StatusIn(BaseModel):
    status: str
    note: Optional[str] = None


class NoteIn(BaseModel):
    text: str


def _job_view(conn, job_id: int) -> dict:
    j = jobs.get_job(conn, job_id)
    j["materials"] = jobs.get_materials(conn, job_id)
    j["history"] = jobs.job_history(conn, job_id)
    return j


@app.get("/api/jobs")
def jobs_list(status: Optional[str] = None, include_closed: bool = True, conn=Depends(db)):
    return jobs.list_jobs(conn, status=status, include_closed=include_closed)


@app.post("/api/jobs", status_code=201)
def jobs_create(body: JobIn, conn=Depends(db)):
    if body.role_id is not None:
        roles.get_role(conn, body.role_id)
    jid = jobs.add_job(
        conn, body.company, body.title, url=body.url, location=body.location,
        role_id=body.role_id, jd_text=body.jd_text, notes=body.notes,
    )
    return _job_view(conn, jid)


@app.get("/api/jobs/funnel")
def jobs_funnel(conn=Depends(db)):
    return jobs.funnel(conn)


@app.get("/api/jobs/{job_id}")
def jobs_get(job_id: int, conn=Depends(db)):
    return _job_view(conn, job_id)


@app.patch("/api/jobs/{job_id}")
def jobs_update(job_id: int, body: JobPatch, conn=Depends(db)):
    jobs.get_job(conn, job_id)
    fields = body.model_dump(exclude_unset=True)
    if "jd_text" in fields and fields["jd_text"] is not None:
        jobs.set_jd(conn, job_id, fields.pop("jd_text"))
    if "role_id" in fields:
        if fields["role_id"] is not None:
            roles.get_role(conn, fields["role_id"])
        jobs.set_role(conn, job_id, fields.pop("role_id"))
    simple = {k: v for k, v in fields.items() if k in ("company", "title", "url", "location") and v is not None}
    if simple:
        assignments = ", ".join(f"{k} = ?" for k in simple)
        conn.execute(f"UPDATE jobs SET {assignments}, updated_at = datetime('now') WHERE id = ?", (*simple.values(), job_id))
        conn.commit()
    return _job_view(conn, job_id)


@app.post("/api/jobs/{job_id}/status")
def jobs_status(job_id: int, body: StatusIn, conn=Depends(db)):
    jobs.set_status(conn, job_id, body.status, body.note)
    return _job_view(conn, job_id)


@app.post("/api/jobs/{job_id}/notes")
def jobs_note(job_id: int, body: NoteIn, conn=Depends(db)):
    jobs.add_note(conn, job_id, body.text)
    return _job_view(conn, job_id)


@app.post("/api/jobs/{job_id}/analyze", status_code=202)
def jobs_analyze(job_id: int, conn=Depends(db)):
    _require_ai(conn)
    j = jobs.get_job(conn, job_id)
    if not j["jd_text"]:
        raise HTTPException(400, "Add a job description before analyzing.")
    if "(ledger is empty)" in ledger.profile_markdown(conn):
        raise HTTPException(400, "Your ledger is empty. Import a resume or add entries first.")
    return _in_task("job_analyze", lambda c: services.analyze_job(c, job_id))


# --- frontend ----------------------------------------------------------------

if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        candidate = STATIC_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")
else:

    @app.get("/", include_in_schema=False)
    def no_frontend():
        return PlainTextResponse(
            "Frontend not built. Run `npm install && npm run build` in jobhunt/web/frontend, "
            "or use the API docs at /api/docs.",
            status_code=200,
        )
