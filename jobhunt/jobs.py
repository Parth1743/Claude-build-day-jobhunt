"""Job tracking: postings, status funnel, analyses and generated materials."""

from __future__ import annotations

import sqlite3

from .db import JOB_STATUSES, dumps, loads, now


def add_job(
    conn: sqlite3.Connection,
    company: str,
    title: str,
    *,
    url: str | None = None,
    location: str | None = None,
    role_id: int | None = None,
    jd_text: str | None = None,
    notes: str | None = None,
) -> int:
    ts = now()
    cur = conn.execute(
        """INSERT INTO jobs (company, title, url, location, role_id, jd_text, status, notes, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, 'saved', ?, ?, ?)""",
        (company.strip(), title.strip(), url, location, role_id, jd_text, notes, ts, ts),
    )
    job_id = cur.lastrowid
    conn.execute(
        "INSERT INTO job_events (job_id, from_status, to_status, note, at) VALUES (?, NULL, 'saved', NULL, ?)",
        (job_id, ts),
    )
    conn.commit()
    return job_id


def _hydrate(row) -> dict:
    job = dict(row)
    job["analysis"] = loads(job.get("analysis"), None)
    return job


def get_job(conn: sqlite3.Connection, job_id: int) -> dict:
    row = conn.execute(
        """SELECT j.*, r.title AS role_title FROM jobs j
           LEFT JOIN target_roles r ON r.id = j.role_id WHERE j.id = ?""",
        (job_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"no job with id {job_id}")
    return _hydrate(row)


def list_jobs(conn: sqlite3.Connection, status: str | None = None, include_closed: bool = True) -> list[dict]:
    clauses, params = [], []
    if status:
        clauses.append("j.status = ?")
        params.append(status)
    if not include_closed:
        clauses.append("j.status NOT IN ('rejected', 'withdrawn')")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        f"""SELECT j.*, r.title AS role_title FROM jobs j
            LEFT JOIN target_roles r ON r.id = j.role_id {where}
            ORDER BY j.updated_at DESC""",
        params,
    ).fetchall()
    return [_hydrate(r) for r in rows]


def set_jd(conn: sqlite3.Connection, job_id: int, jd_text: str) -> None:
    conn.execute("UPDATE jobs SET jd_text = ?, updated_at = ? WHERE id = ?", (jd_text, now(), job_id))
    conn.commit()


def set_role(conn: sqlite3.Connection, job_id: int, role_id: int | None) -> None:
    conn.execute("UPDATE jobs SET role_id = ?, updated_at = ? WHERE id = ?", (role_id, now(), job_id))
    conn.commit()


def set_status(conn: sqlite3.Connection, job_id: int, status: str, note: str | None = None) -> None:
    if status not in JOB_STATUSES:
        raise ValueError(f"status must be one of {', '.join(JOB_STATUSES)}")
    job = get_job(conn, job_id)
    ts = now()
    applied_at = job["applied_at"]
    if status == "applied" and not applied_at:
        applied_at = ts
    conn.execute(
        "UPDATE jobs SET status = ?, applied_at = ?, updated_at = ? WHERE id = ?",
        (status, applied_at, ts, job_id),
    )
    conn.execute(
        "INSERT INTO job_events (job_id, from_status, to_status, note, at) VALUES (?, ?, ?, ?, ?)",
        (job_id, job["status"], status, note, ts),
    )
    conn.commit()


def add_note(conn: sqlite3.Connection, job_id: int, note: str) -> None:
    job = get_job(conn, job_id)
    ts = now()
    existing = (job["notes"] or "").rstrip()
    combined = f"{existing}\n[{ts[:10]}] {note}".strip()
    conn.execute("UPDATE jobs SET notes = ?, updated_at = ? WHERE id = ?", (combined, ts, job_id))
    conn.commit()


def save_analysis(conn: sqlite3.Connection, job_id: int, analysis: dict, fit_score: int) -> None:
    conn.execute(
        "UPDATE jobs SET analysis = ?, fit_score = ?, updated_at = ? WHERE id = ?",
        (dumps(analysis), int(fit_score), now(), job_id),
    )
    conn.commit()


def add_material(conn: sqlite3.Connection, job_id: int, kind: str, content: str) -> int:
    cur = conn.execute(
        "INSERT INTO materials (job_id, kind, content, created_at) VALUES (?, ?, ?, ?)",
        (job_id, kind, content, now()),
    )
    conn.commit()
    return cur.lastrowid


def get_materials(conn: sqlite3.Connection, job_id: int) -> list[dict]:
    rows = conn.execute("SELECT * FROM materials WHERE job_id = ? ORDER BY id", (job_id,)).fetchall()
    return [dict(r) for r in rows]


def job_history(conn: sqlite3.Connection, job_id: int) -> list[dict]:
    rows = conn.execute("SELECT * FROM job_events WHERE job_id = ? ORDER BY id", (job_id,)).fetchall()
    return [dict(r) for r in rows]


def funnel(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status").fetchall()
    counts = {s: 0 for s in JOB_STATUSES}
    for r in rows:
        counts[r["status"]] = r["n"]
    return counts
