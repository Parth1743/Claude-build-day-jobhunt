"""Tiny in-process background task registry for long AI calls.

Each task runs in its own thread with its own SQLite connection. Clients poll
GET /api/tasks/{id} until status is done or error.
"""

from __future__ import annotations

import threading
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from ..db import now


@dataclass
class Task:
    id: str
    kind: str
    status: str = "running"  # running | done | error
    result: Any = None
    error: str | None = None
    created_at: str = field(default_factory=now)
    finished_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


_tasks: dict[str, Task] = {}
_lock = threading.Lock()
MAX_TASKS = 200


def start(kind: str, fn: Callable[[], Any]) -> Task:
    task = Task(id=uuid.uuid4().hex[:12], kind=kind)
    with _lock:
        _tasks[task.id] = task
        if len(_tasks) > MAX_TASKS:
            for old in sorted(_tasks.values(), key=lambda t: t.created_at)[: len(_tasks) - MAX_TASKS]:
                if old.status != "running":
                    _tasks.pop(old.id, None)

    def run():
        try:
            task.result = fn()
            task.status = "done"
        except Exception as e:  # noqa: BLE001 - surfaced to the client
            task.error = str(e) or e.__class__.__name__
            task.status = "error"
            traceback.print_exc()
        finally:
            task.finished_at = now()

    threading.Thread(target=run, daemon=True, name=f"task-{kind}-{task.id}").start()
    return task


def get(task_id: str) -> Task | None:
    with _lock:
        return _tasks.get(task_id)


def recent(limit: int = 20) -> list[Task]:
    with _lock:
        return sorted(_tasks.values(), key=lambda t: t.created_at, reverse=True)[:limit]
