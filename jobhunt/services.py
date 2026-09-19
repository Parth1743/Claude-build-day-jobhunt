"""Use cases shared by the CLI and the web API.

These functions combine storage modules with the AI layer and file output so
both front ends behave identically.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from . import config, jobs, ledger, roles, settings
from .db import LEDGER_KINDS, SKILL_LEVELS


class ServiceError(ValueError):
    """User-facing failure (missing data, bad state)."""


def ai_config(conn: sqlite3.Connection) -> settings.ProviderConfig:
    """Resolve the active provider or explain how to configure one."""
    cfg = settings.resolve(conn)
    if not cfg.api_key:
        env_names = " or ".join(settings.PROVIDERS[cfg.provider].env_keys)
        raise ServiceError(
            f"No API key for {cfg.label}. Add one on the Settings page, or set {env_names} in .env and restart."
        )
    return cfg


def test_ai(conn: sqlite3.Connection) -> dict:
    from . import providers

    return providers.test_connection(ai_config(conn))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def _profile_or_fail(conn: sqlite3.Connection) -> str:
    profile = ledger.profile_markdown(conn)
    if "(ledger is empty)" in profile:
        raise ServiceError("Your ledger is empty. Import a resume or add entries first.")
    return profile


# --- ledger import -----------------------------------------------------------


def extract_resume_entries(conn: sqlite3.Connection, text: str) -> dict:
    from . import ai

    extracted = ai.extract_resume(ai_config(conn), text)
    return {"entries": [e.model_dump() for e in extracted.entries], "notes": extracted.notes}


def commit_entries(conn: sqlite3.Connection, entries: list[dict], source: str) -> tuple[int, list[str]]:
    saved, skipped = 0, []
    for e in entries:
        kind = e.get("kind") if e.get("kind") in LEDGER_KINDS else "achievement"
        level = e.get("level") if e.get("level") in SKILL_LEVELS else None
        try:
            ledger.add_entry(
                conn, kind, e["title"], org=e.get("org"), start_date=e.get("start_date"),
                end_date=e.get("end_date"), description=e.get("description"), skills=e.get("skills") or [],
                level=level, url=e.get("url"), source=source,
            )
            saved += 1
        except (ValueError, KeyError) as ex:
            skipped.append(f"{e.get('title', '?')}: {ex}")
    return saved, skipped


# --- roles -------------------------------------------------------------------


def suggest_role_skills(conn: sqlite3.Connection, title: str, hint: str | None) -> dict:
    from . import ai

    return ai.role_skills(ai_config(conn), title, hint).model_dump()


# --- jobs --------------------------------------------------------------------


def analyze_job(conn: sqlite3.Connection, job_id: int) -> dict:
    """Run the fit analysis, store it, save materials and write Markdown files."""
    from . import ai

    j = jobs.get_job(conn, job_id)
    if not j["jd_text"]:
        raise ServiceError(f"Job #{job_id} has no description yet.")
    profile = _profile_or_fail(conn)

    a = ai.analyze_job(ai_config(conn), profile, j["company"], j["title"], j["jd_text"])
    analysis = a.model_dump()
    jobs.save_analysis(conn, job_id, analysis, a.fit_score)

    bullets_md = "\n".join(f"- {b.bullet}  \n  _from: {b.ledger_ref}_" for b in a.tailored_bullets)
    jobs.add_material(conn, job_id, "bullets", bullets_md)
    jobs.add_material(conn, job_id, "cover_letter", a.cover_letter)

    folder = config.out_dir() / f"{job_id:03d}-{_slug(j['company'])}-{_slug(j['title'])}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "analysis.md").write_text(_analysis_markdown(j, analysis), encoding="utf-8")
    (folder / "bullets.md").write_text(f"# Tailored bullets\n\n{bullets_md}\n", encoding="utf-8")
    (folder / "cover_letter.md").write_text(a.cover_letter + "\n", encoding="utf-8")

    return {"analysis": analysis, "bullets_md": bullets_md, "folder": str(folder)}


def _analysis_markdown(job: dict, a: dict) -> str:
    def bullets(items):
        return "\n".join(f"- {s}" for s in items) or "- none"

    return (
        f"# {job['title']} at {job['company']}\n\n**Fit: {a['fit_score']}/100**\n\n{a['fit_summary']}\n\n"
        f"## Matched\n{bullets(a['matched_skills'])}\n\n"
        f"## Missing\n{bullets(a['missing_skills'])}\n\n"
        f"## Keywords to mirror\n{bullets(a['keywords_to_include'])}\n\n"
        f"## Red flags\n{bullets(a['red_flags'])}\n"
    )


# --- roadmap -----------------------------------------------------------------


def generate_roadmap(
    conn: sqlite3.Connection, role: dict, hours: int, weeks: int, include_jobs: bool = True
) -> dict:
    from . import ai

    profile = _profile_or_fail(conn)
    jds: list[str] = []
    if include_jobs:
        jds = [j["jd_text"] for j in jobs.list_jobs(conn) if j["role_id"] == role["id"] and j["jd_text"]][:5]
    plan = ai.build_roadmap(ai_config(conn), profile, role, jds, hours, weeks)
    items = [i.model_dump() for i in plan.items]
    for it in items:
        it["actions"] = it["actions"] + [f"Proof: {it.pop('proof')}"]
    ids = roles.replace_roadmap(conn, role["id"], items)
    return {"summary": plan.summary, "leverage_existing": plan.leverage_existing, "item_ids": ids}


def complete_roadmap_item(
    conn: sqlite3.Connection,
    item_id: int,
    *,
    level: str | None = "intermediate",
    proof: str | None = None,
    add_to_ledger: bool = True,
) -> int | None:
    """Mark done and, unless told otherwise, record the skill in the ledger."""
    i = roles.get_item(conn, item_id)
    roles.set_item_status(conn, item_id, "done")
    if not add_to_ledger:
        return None
    return ledger.add_entry(
        conn, "skill", i["skill"], level=level, url=proof,
        description=f"Learned via roadmap item #{item_id}. {i['why'] or ''}".strip(),
        source=f"roadmap:{item_id}",
    )
