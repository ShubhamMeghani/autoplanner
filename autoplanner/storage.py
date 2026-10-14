"""Storage: the repository interface, planner IDs, and in-memory and Supabase repositories
(R2-R8, R47). Every read and write is scoped to one planner ID (R6)."""

from __future__ import annotations

import copy
import re
import secrets
from datetime import date, datetime, time
from typing import Protocol

from autoplanner.config import TZ
from autoplanner.models import Block, Event, PlannerState, Preferences, Task

PLANNER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")


def new_planner_id() -> str:
    """256 bits from a CSPRNG, 43 URL-safe characters (R2)."""
    return secrets.token_urlsafe(32)


def is_valid_planner_id(value: str | None) -> bool:
    return bool(value) and PLANNER_ID_RE.fullmatch(value) is not None


class StorageUnavailable(Exception):
    """Supabase is not configured or cannot be reached (R7)."""


class Repository(Protocol):
    def create_planner(self, prefs: Preferences) -> str: ...
    def planner_exists(self, planner_id: str) -> bool: ...
    def load(self, planner_id: str) -> PlannerState: ...
    def save_prefs(self, planner_id: str, prefs: Preferences, meta: dict) -> None: ...
    def upsert_events(self, planner_id: str, events: list[Event]) -> None: ...
    def delete_events(self, planner_id: str, ids: list[str]) -> None: ...
    def upsert_tasks(self, planner_id: str, tasks: list[Task]) -> None: ...
    def delete_tasks(self, planner_id: str, ids: list[str]) -> None: ...
    def upsert_blocks(self, planner_id: str, blocks: list[Block]) -> None: ...
    def delete_blocks(self, planner_id: str, ids: list[str]) -> None: ...
    def delete_planner(self, planner_id: str) -> None: ...
    def count_gemini_calls(self, planner_id: str, since: datetime) -> int: ...
    def log_import(self, planner_id: str, engine: str) -> None: ...


def save_changes(repo: Repository, planner_id: str, old: PlannerState, new: PlannerState) -> None:
    """Persist the difference between two states.

    New and changed rows are written first, deletions next, and the plan metadata last. If a
    write fails, the stored input hash still describes the old state, so the next load replans.
    """
    def diff(old_items, new_items):
        before = {x.id: x for x in old_items}
        after = {x.id: x for x in new_items}
        changed = [x for i, x in after.items() if before.get(i) != x]
        removed = [i for i in before if i not in after]
        return changed, removed

    events_changed, events_removed = diff(old.events, new.events)
    tasks_changed, tasks_removed = diff(old.tasks, new.tasks)
    blocks_changed, blocks_removed = diff(old.blocks, new.blocks)
    if events_changed:
        repo.upsert_events(planner_id, events_changed)
    if tasks_changed:
        repo.upsert_tasks(planner_id, tasks_changed)
    if blocks_changed:
        repo.upsert_blocks(planner_id, blocks_changed)
    if blocks_removed:
        repo.delete_blocks(planner_id, blocks_removed)
    if tasks_removed:
        repo.delete_tasks(planner_id, tasks_removed)
    if events_removed:
        repo.delete_events(planner_id, events_removed)
    if old.prefs != new.prefs or old.meta != new.meta:
        repo.save_prefs(planner_id, new.prefs, new.meta)


class MemoryRepo:
    """In-process repository: demo mode (R52) and tests (R60). Same contract as SupabaseRepo."""

    def __init__(self) -> None:
        self._planners: dict[str, dict] = {}
        self._imports: list[tuple[str, datetime, str]] = []

    def _get(self, planner_id: str) -> dict:
        if planner_id not in self._planners:
            raise KeyError("planner not found")
        return self._planners[planner_id]

    def create_planner(self, prefs: Preferences, planner_id: str | None = None) -> str:
        planner_id = planner_id or new_planner_id()
        self._planners[planner_id] = {"prefs": prefs, "meta": {}, "events": {}, "tasks": {}, "blocks": {}}
        return planner_id

    def planner_exists(self, planner_id: str) -> bool:
        return planner_id in self._planners

    def load(self, planner_id: str) -> PlannerState:
        p = self._get(planner_id)
        return PlannerState(prefs=p["prefs"], events=list(p["events"].values()), tasks=list(p["tasks"].values()),
                            blocks=list(p["blocks"].values()), meta=copy.deepcopy(p["meta"]))

    def save_prefs(self, planner_id: str, prefs: Preferences, meta: dict) -> None:
        p = self._get(planner_id)
        p["prefs"], p["meta"] = prefs, copy.deepcopy(meta)

    def _upsert(self, planner_id: str, kind: str, items) -> None:
        store = self._get(planner_id)[kind]
        for item in items:
            store[item.id] = item

    def _delete(self, planner_id: str, kind: str, ids) -> None:
        store = self._get(planner_id)[kind]
        for i in ids:
            store.pop(i, None)
        if kind == "tasks":  # mirror ON DELETE CASCADE
            blocks = self._get(planner_id)["blocks"]
            for bid in [b.id for b in blocks.values() if b.task_id in set(ids)]:
                del blocks[bid]

    def upsert_events(self, planner_id, events): self._upsert(planner_id, "events", events)
    def delete_events(self, planner_id, ids): self._delete(planner_id, "events", ids)
    def upsert_tasks(self, planner_id, tasks): self._upsert(planner_id, "tasks", tasks)
    def delete_tasks(self, planner_id, ids): self._delete(planner_id, "tasks", ids)
    def upsert_blocks(self, planner_id, blocks): self._upsert(planner_id, "blocks", blocks)
    def delete_blocks(self, planner_id, ids): self._delete(planner_id, "blocks", ids)

    def delete_planner(self, planner_id: str) -> None:
        self._planners.pop(planner_id, None)
        self._imports = [row for row in self._imports if row[0] != planner_id]

    def count_gemini_calls(self, planner_id: str, since: datetime) -> int:
        return sum(1 for pid, at, engine in self._imports if pid == planner_id and engine == "gemini" and at >= since)

    def log_import(self, planner_id: str, engine: str, at: datetime | None = None) -> None:
        self._imports.append((planner_id, at or datetime.now(TZ), engine))


# ---------- Supabase ----------

def _time_out(value: time) -> str:
    return "24:00:00" if value == time.max else value.strftime("%H:%M:%S")


def _time_in(value: str) -> time:
    return time.max if value.startswith("24:") else time.fromisoformat(value)


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value).astimezone(TZ) if value else None


class SupabaseRepo:
    """Supabase Postgres through PostgREST, with the server-side secret key (R6).

    Every query filters on planner_id. The plan metadata is kept in planners.prefs under
    "_meta". Any client error becomes StorageUnavailable, with no row data in the message.
    """

    def __init__(self, client) -> None:
        self.db = client

    @classmethod
    def from_secrets(cls) -> SupabaseRepo:
        from autoplanner.config import get_secret

        url, key = get_secret("SUPABASE_URL"), get_secret("SUPABASE_KEY")
        if not (url and key):
            raise StorageUnavailable("Supabase is not configured")
        try:
            from supabase import create_client

            return cls(create_client(url, key))
        except Exception as exc:
            raise StorageUnavailable(type(exc).__name__) from None

    def _run(self, query):
        try:
            return query.execute()
        except Exception as exc:
            raise StorageUnavailable(type(exc).__name__) from None

    def _table(self, name: str):
        return self.db.table(name)

    def create_planner(self, prefs: Preferences) -> str:
        planner_id = new_planner_id()
        self._run(self._table("planners").insert({"id": planner_id, "prefs": prefs.to_dict()}))
        return planner_id

    def planner_exists(self, planner_id: str) -> bool:
        rows = self._run(self._table("planners").select("id").eq("id", planner_id).limit(1)).data
        return bool(rows)

    def load(self, planner_id: str) -> PlannerState:
        rows = self._run(self._table("planners").select("prefs").eq("id", planner_id).limit(1)).data
        if not rows:
            raise KeyError("planner not found")
        stored = dict(rows[0]["prefs"] or {})
        meta = stored.pop("_meta", {}) or {}
        events = self._run(self._table("events").select("*").eq("planner_id", planner_id)).data
        tasks = self._run(self._table("tasks").select("*").eq("planner_id", planner_id)).data
        blocks = self._run(self._table("blocks").select("*").eq("planner_id", planner_id)).data
        return PlannerState(
            prefs=Preferences.from_dict(stored),
            events=[Event(id=r["id"], title=r["title"], kind=r["kind"], start_time=_time_in(r["start_time"]),
                          end_time=_time_in(r["end_time"]),
                          on_date=date.fromisoformat(r["on_date"]) if r["on_date"] else None,
                          weekdays=tuple(r["weekdays"]) if r["weekdays"] is not None else None,
                          until_date=date.fromisoformat(r["until_date"]) if r["until_date"] else None)
                    for r in events],
            tasks=[Task(id=r["id"], title=r["title"], course=r["course"], type=r["type"],
                        est_hours_raw=float(r["est_hours_raw"]), est_hours=float(r["est_hours"]),
                        deadline=_dt(r["deadline"]), demanding=r["demanding"], status=r["status"],
                        source=r["source"],
                        actual_hours=float(r["actual_hours"]) if r["actual_hours"] is not None else None,
                        learning_eligible=r["learning_eligible"], created_at=_dt(r["created_at"]),
                        completed_at=_dt(r["completed_at"]))
                   for r in tasks],
            blocks=[Block(id=r["id"], task_id=r["task_id"], start=_dt(r["start_at"]), end=_dt(r["end_at"]),
                          status=r["status"], actual_minutes=r["actual_minutes"], plan_version=r["plan_version"])
                    for r in blocks],
            meta=meta,
        )

    def save_prefs(self, planner_id: str, prefs: Preferences, meta: dict) -> None:
        self._run(self._table("planners").update(
            {"prefs": {**prefs.to_dict(), "_meta": meta}, "updated_at": datetime.now(TZ).isoformat()}
        ).eq("id", planner_id))

    def upsert_events(self, planner_id: str, events: list[Event]) -> None:
        self._run(self._table("events").upsert([{
            "id": e.id, "planner_id": planner_id, "title": e.title, "kind": e.kind,
            "start_time": _time_out(e.start_time), "end_time": _time_out(e.end_time),
            "on_date": e.on_date.isoformat() if e.on_date else None,
            "weekdays": list(e.weekdays) if e.weekdays is not None else None,
            "until_date": e.until_date.isoformat() if e.until_date else None,
        } for e in events]))

    def upsert_tasks(self, planner_id: str, tasks: list[Task]) -> None:
        self._run(self._table("tasks").upsert([{
            "id": t.id, "planner_id": planner_id, "title": t.title, "course": t.course, "type": t.type,
            "est_hours_raw": t.est_hours_raw, "est_hours": t.est_hours, "deadline": t.deadline.isoformat(),
            "demanding": t.demanding, "status": t.status, "source": t.source, "actual_hours": t.actual_hours,
            "learning_eligible": t.learning_eligible,
            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        } for t in tasks]))

    def upsert_blocks(self, planner_id: str, blocks: list[Block]) -> None:
        self._run(self._table("blocks").upsert([{
            "id": b.id, "planner_id": planner_id, "task_id": b.task_id, "start_at": b.start.isoformat(),
            "end_at": b.end.isoformat(), "status": b.status, "actual_minutes": b.actual_minutes,
            "plan_version": b.plan_version,
        } for b in blocks]))

    def _delete(self, table: str, planner_id: str, ids: list[str]) -> None:
        self._run(self._table(table).delete().eq("planner_id", planner_id).in_("id", ids))

    def delete_events(self, planner_id, ids): self._delete("events", planner_id, ids)
    def delete_tasks(self, planner_id, ids): self._delete("tasks", planner_id, ids)
    def delete_blocks(self, planner_id, ids): self._delete("blocks", planner_id, ids)

    def delete_planner(self, planner_id: str) -> None:
        self._run(self._table("planners").delete().eq("id", planner_id))

    def count_gemini_calls(self, planner_id: str, since: datetime) -> int:
        result = self._run(self._table("import_log").select("id", count="exact").eq("planner_id", planner_id)
                           .eq("engine", "gemini").gte("created_at", since.isoformat()).limit(1))
        return result.count or 0

    def log_import(self, planner_id: str, engine: str) -> None:
        self._run(self._table("import_log").insert({"planner_id": planner_id, "engine": engine}))


# ---------- which repository the app uses ----------

_override: Repository | None = None
_supabase: SupabaseRepo | None = None


def get_repo() -> Repository:
    """The app's repository: Supabase, created once per process, or a test override."""
    global _supabase
    if _override is not None:
        return _override
    if _supabase is None:
        _supabase = SupabaseRepo.from_secrets()
    return _supabase


def set_repo_override(repo: Repository | None) -> None:
    """Tests only: make get_repo() return `repo` (None restores Supabase)."""
    global _override
    _override = repo
