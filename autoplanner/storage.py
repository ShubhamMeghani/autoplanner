"""Storage: the repository interface, planner IDs, and in-memory and Supabase repositories
(R2-R8, R47). Every read and write is scoped to one planner ID (R6)."""

from __future__ import annotations

import copy
import re
import secrets
from datetime import datetime
from typing import Protocol

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
    """Persist the difference between two states. Children are written after their parents."""
    if old.prefs != new.prefs or old.meta != new.meta:
        repo.save_prefs(planner_id, new.prefs, new.meta)

    def diff(old_items, new_items):
        before = {x.id: x for x in old_items}
        after = {x.id: x for x in new_items}
        changed = [x for i, x in after.items() if before.get(i) != x]
        removed = [i for i in before if i not in after]
        return changed, removed

    events_changed, events_removed = diff(old.events, new.events)
    tasks_changed, tasks_removed = diff(old.tasks, new.tasks)
    blocks_changed, blocks_removed = diff(old.blocks, new.blocks)
    if blocks_removed:
        repo.delete_blocks(planner_id, blocks_removed)
    if tasks_removed:
        repo.delete_tasks(planner_id, tasks_removed)
    if events_removed:
        repo.delete_events(planner_id, events_removed)
    if events_changed:
        repo.upsert_events(planner_id, events_changed)
    if tasks_changed:
        repo.upsert_tasks(planner_id, tasks_changed)
    if blocks_changed:
        repo.upsert_blocks(planner_id, blocks_changed)


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
        from autoplanner.config import TZ

        self._imports.append((planner_id, at or datetime.now(TZ), engine))
