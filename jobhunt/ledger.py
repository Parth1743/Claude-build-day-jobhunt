"""The ledger: an append-only record of experience, skills, certifications and more.

Entries are the current state. Every create/update/retire also writes a
ledger_events row with a full snapshot, so history is never lost.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict

from .db import LEDGER_KINDS, SKILL_LEVELS, dumps, loads, now

_LEVEL_RANK = {lvl: i for i, lvl in enumerate(SKILL_LEVELS)}


def _snapshot(conn: sqlite3.Connection, entry_id: int, action: str, source: str) -> None:
    row = conn.execute("SELECT * FROM ledger_entries WHERE id = ?", (entry_id,)).fetchone()
    conn.execute(
        "INSERT INTO ledger_events (entry_id, action, source, snapshot, at) VALUES (?, ?, ?, ?, ?)",
        (entry_id, action, source, dumps(dict(row)), now()),
    )


def clean_skills(skills) -> list[str]:
    seen: dict[str, str] = {}
    for s in skills or []:
        s = str(s).strip()
        if s and s.lower() not in seen:
            seen[s.lower()] = s
    return list(seen.values())


def add_entry(
    conn: sqlite3.Connection,
    kind: str,
    title: str,
    *,
    org: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    description: str | None = None,
    skills: list[str] | None = None,
    level: str | None = None,
    url: str | None = None,
    source: str = "manual",
) -> int:
    if kind not in LEDGER_KINDS:
        raise ValueError(f"kind must be one of {', '.join(LEDGER_KINDS)}")
    if level is not None and level not in SKILL_LEVELS:
        raise ValueError(f"level must be one of {', '.join(SKILL_LEVELS)}")
    ts = now()
    cur = conn.execute(
        """INSERT INTO ledger_entries
           (kind, title, org, start_date, end_date, description, skills, level, url, active, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
        (kind, title.strip(), org, start_date, end_date, description, dumps(clean_skills(skills)), level, url, ts, ts),
    )
    entry_id = cur.lastrowid
    _snapshot(conn, entry_id, "create", source)
    conn.commit()
    return entry_id


_EDITABLE = {"title", "org", "start_date", "end_date", "description", "skills", "level", "url", "kind"}


def update_entry(conn: sqlite3.Connection, entry_id: int, source: str = "manual", **fields) -> None:
    fields = {k: v for k, v in fields.items() if v is not None}
    bad = set(fields) - _EDITABLE
    if bad:
        raise ValueError(f"cannot edit fields: {', '.join(sorted(bad))}")
    if not fields:
        return
    if "kind" in fields and fields["kind"] not in LEDGER_KINDS:
        raise ValueError(f"kind must be one of {', '.join(LEDGER_KINDS)}")
    if "level" in fields and fields["level"] not in SKILL_LEVELS:
        raise ValueError(f"level must be one of {', '.join(SKILL_LEVELS)}")
    if "skills" in fields:
        fields["skills"] = dumps(clean_skills(fields["skills"]))
    fields["updated_at"] = now()
    assignments = ", ".join(f"{k} = ?" for k in fields)
    cur = conn.execute(
        f"UPDATE ledger_entries SET {assignments} WHERE id = ?", (*fields.values(), entry_id)
    )
    if cur.rowcount == 0:
        raise KeyError(f"no ledger entry with id {entry_id}")
    _snapshot(conn, entry_id, "update", source)
    conn.commit()


def retire_entry(conn: sqlite3.Connection, entry_id: int, source: str = "manual") -> None:
    cur = conn.execute(
        "UPDATE ledger_entries SET active = 0, updated_at = ? WHERE id = ?", (now(), entry_id)
    )
    if cur.rowcount == 0:
        raise KeyError(f"no ledger entry with id {entry_id}")
    _snapshot(conn, entry_id, "retire", source)
    conn.commit()


def _hydrate(row) -> dict:
    d = dict(row)
    d["skills"] = loads(d["skills"], [])
    return d


def get_entry(conn: sqlite3.Connection, entry_id: int) -> dict:
    row = conn.execute("SELECT * FROM ledger_entries WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        raise KeyError(f"no ledger entry with id {entry_id}")
    return _hydrate(row)


def list_entries(conn: sqlite3.Connection, kind: str | None = None, include_inactive: bool = False) -> list[dict]:
    clauses, params = [], []
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    if not include_inactive:
        clauses.append("active = 1")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM ledger_entries {where} "
        "ORDER BY kind, COALESCE(end_date, '9999') DESC, start_date DESC, id",
        params,
    ).fetchall()
    return [_hydrate(r) for r in rows]


def history(conn: sqlite3.Connection, entry_id: int | None = None, limit: int = 50) -> list[dict]:
    if entry_id is None:
        rows = conn.execute("SELECT * FROM ledger_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM ledger_events WHERE entry_id = ? ORDER BY id DESC LIMIT ?", (entry_id, limit)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["snapshot"] = loads(d["snapshot"], {})
        out.append(d)
    return out


def skill_map(conn: sqlite3.Connection) -> dict[str, dict]:
    """Aggregate every skill mentioned across active entries.

    Returns {skill_key: {"name", "level", "evidence": [entry labels]}}.
    A dedicated `skill` entry sets the level; other entries only add evidence.
    """
    agg: dict[str, dict] = {}
    evidence: dict[str, list[str]] = defaultdict(list)
    for e in list_entries(conn):
        if e["kind"] == "skill":
            key = e["title"].lower()
            current = agg.get(key)
            new_rank = _LEVEL_RANK.get(e["level"] or "", -1)
            cur_rank = _LEVEL_RANK.get(current["level"] or "", -1) if current else -2
            if current is None or new_rank > cur_rank:
                agg[key] = {"name": e["title"], "level": e["level"]}
        for s in e["skills"]:
            key = s.lower()
            agg.setdefault(key, {"name": s, "level": None})
            label = e["title"] if not e["org"] else f"{e['title']} @ {e['org']}"
            if e["kind"] != "skill":
                evidence[key].append(label)
    for key, val in agg.items():
        val["evidence"] = evidence.get(key, [])
    return dict(sorted(agg.items(), key=lambda kv: kv[1]["name"].lower()))


def profile_markdown(conn: sqlite3.Connection) -> str:
    """Render the active ledger as Markdown. Used for exports and as model context."""
    entries = list_entries(conn)
    if not entries:
        return "# Profile\n\n(ledger is empty)\n"
    sections = {
        "experience": "Experience",
        "project": "Projects",
        "education": "Education",
        "certification": "Certifications",
        "achievement": "Achievements",
    }
    lines = ["# Profile", ""]
    for kind, heading in sections.items():
        items = [e for e in entries if e["kind"] == kind]
        if not items:
            continue
        lines += [f"## {heading}", ""]
        for e in items:
            head = f"**{e['title']}**"
            if e["org"]:
                head += f" - {e['org']}"
            end = e["end_date"] or ("present" if e["start_date"] else None)
            dates = " to ".join(x for x in (e["start_date"], end) if x)
            if dates:
                head += f" ({dates})"
            lines.append(f"- {head}")
            if e["description"]:
                for para in e["description"].strip().splitlines():
                    if para.strip():
                        lines.append(f"  {para.strip()}")
            if e["skills"]:
                lines.append(f"  Skills: {', '.join(e['skills'])}")
            if e["url"]:
                lines.append(f"  Link: {e['url']}")
        lines.append("")
    skills = skill_map(conn)
    if skills:
        lines += ["## Skills", ""]
        for s in skills.values():
            lvl = f" ({s['level']})" if s["level"] else ""
            ev = f" - used in: {'; '.join(s['evidence'][:3])}" if s["evidence"] else ""
            lines.append(f"- {s['name']}{lvl}{ev}")
        lines.append("")
    return "\n".join(lines)
