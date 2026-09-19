"""Target roles and the skill-up roadmap attached to each role."""

from __future__ import annotations

import sqlite3

from .db import ROADMAP_STATUSES, dumps, loads, now


def add_role(
    conn: sqlite3.Connection,
    title: str,
    *,
    description: str | None = None,
    required_skills: list[str] | None = None,
    nice_to_have: list[str] | None = None,
    priority: int = 1,
) -> int:
    cur = conn.execute(
        """INSERT INTO target_roles (title, description, required_skills, nice_to_have, priority, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (title.strip(), description, dumps(required_skills or []), dumps(nice_to_have or []), priority, now()),
    )
    conn.commit()
    return cur.lastrowid


def update_role(
    conn: sqlite3.Connection,
    role_id: int,
    *,
    description: str | None = None,
    required_skills: list[str] | None = None,
    nice_to_have: list[str] | None = None,
    priority: int | None = None,
) -> None:
    fields: dict = {}
    if description is not None:
        fields["description"] = description
    if required_skills is not None:
        fields["required_skills"] = dumps(required_skills)
    if nice_to_have is not None:
        fields["nice_to_have"] = dumps(nice_to_have)
    if priority is not None:
        fields["priority"] = priority
    if not fields:
        return
    assignments = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE target_roles SET {assignments} WHERE id = ?", (*fields.values(), role_id))
    conn.commit()


def _hydrate(row) -> dict:
    d = dict(row)
    d["required_skills"] = loads(d["required_skills"], [])
    d["nice_to_have"] = loads(d["nice_to_have"], [])
    return d


def get_role(conn: sqlite3.Connection, ref: str | int) -> dict:
    """Look a role up by numeric id or by case-insensitive title."""
    row = None
    if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
        row = conn.execute("SELECT * FROM target_roles WHERE id = ?", (int(ref),)).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT * FROM target_roles WHERE lower(title) = lower(?)", (str(ref),)
        ).fetchone()
    if row is None:
        raise KeyError(f"no target role matching {ref!r}")
    return _hydrate(row)


def list_roles(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM target_roles ORDER BY priority, title").fetchall()
    return [_hydrate(r) for r in rows]


# --- roadmap -----------------------------------------------------------------


def replace_roadmap(conn: sqlite3.Connection, role_id: int, items: list[dict]) -> list[int]:
    """Replace open items for a role. Items already done or skipped are kept."""
    conn.execute(
        "DELETE FROM roadmap_items WHERE role_id = ? AND status IN ('todo', 'in_progress')", (role_id,)
    )
    ts = now()
    ids = []
    for it in items:
        cur = conn.execute(
            """INSERT INTO roadmap_items
               (role_id, skill, priority, why, actions, resources, est_weeks, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'todo', ?, ?)""",
            (
                role_id,
                it["skill"],
                int(it.get("priority", 1)),
                it.get("why"),
                dumps(it.get("actions", [])),
                dumps(it.get("resources", [])),
                it.get("est_weeks"),
                ts,
                ts,
            ),
        )
        ids.append(cur.lastrowid)
    conn.commit()
    return ids


def _hydrate_item(row) -> dict:
    d = dict(row)
    d["actions"] = loads(d["actions"], [])
    d["resources"] = loads(d["resources"], [])
    return d


def list_roadmap(conn: sqlite3.Connection, role_id: int, include_closed: bool = False) -> list[dict]:
    where = "" if include_closed else "AND status IN ('todo', 'in_progress')"
    rows = conn.execute(
        f"SELECT * FROM roadmap_items WHERE role_id = ? {where} "
        "ORDER BY status IN ('done', 'skipped'), priority, id",
        (role_id,),
    ).fetchall()
    return [_hydrate_item(r) for r in rows]


def get_item(conn: sqlite3.Connection, item_id: int) -> dict:
    row = conn.execute("SELECT * FROM roadmap_items WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise KeyError(f"no roadmap item with id {item_id}")
    return _hydrate_item(row)


def set_item_status(conn: sqlite3.Connection, item_id: int, status: str) -> None:
    if status not in ROADMAP_STATUSES:
        raise ValueError(f"status must be one of {', '.join(ROADMAP_STATUSES)}")
    cur = conn.execute(
        "UPDATE roadmap_items SET status = ?, updated_at = ? WHERE id = ?", (status, now(), item_id)
    )
    if cur.rowcount == 0:
        raise KeyError(f"no roadmap item with id {item_id}")
    conn.commit()
