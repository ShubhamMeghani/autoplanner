"""Planning orchestration: remaining work, overdue tasks, the solver problem, and the
strict -> fallback -> validate pipeline (R14, R17, R19, R20, R25, R33)."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import time as clock
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime

from autoplanner import solver as solver_mod
from autoplanner.baseline import greedy_plan, hint_plan
from autoplanner.config import SLOT_MINUTES, SOLVER_TIME_LIMIT_S, SOLVER_WORKERS, TZ
from autoplanner.models import Block, Diagnosis, Event, Plan, PlannerState, Preferences, Task
from autoplanner.solver import blocks_from_assignment
from autoplanner.storage import save_changes
from autoplanner.timegrid import Job, Problem, build_grid, horizon_end, to_ist
from autoplanner.validate import ValidationResult, validate


class PlanValidationError(Exception):
    """A produced plan broke a rule of its rule set (R20). The previous plan is kept."""

    def __init__(self, failures: list[str]):
        super().__init__("; ".join(failures[:5]))
        self.failures = failures


@dataclass
class PlanOutcome:
    plan: Plan
    diagnosis: Diagnosis | None
    validation: ValidationResult
    problem: Problem


def done_minutes(task_id: str, blocks: list[Block], now: datetime) -> int:
    return sum(b.done_minutes(now) for b in blocks if b.task_id == task_id)


def remaining_minutes(task: Task, blocks: list[Block], now: datetime) -> int:
    return max(0, task.est_minutes - done_minutes(task.id, blocks, now))


def refresh_overdue(tasks: list[Task], blocks: list[Block], now: datetime) -> list[Task]:
    """R33: an open task past its deadline with work left becomes overdue."""
    out = []
    for task in tasks:
        if task.status == "open" and task.deadline <= now and remaining_minutes(task, blocks, now) > 0:
            task = replace(task, status="overdue")
        out.append(task)
    return out


def build_problem(now: datetime, prefs: Preferences, events: list[Event], tasks: list[Task],
                  blocks: list[Block]) -> Problem:
    now = to_ist(now)
    in_progress = [(b.start, b.end) for b in blocks
                   if b.start < now < b.end and b.status in ("planned", "done")]
    grid = build_grid(now, prefs, events, in_progress)
    horizon_hours = (grid.end - now).total_seconds() / 3600
    min_block_slots = prefs.min_block_min // SLOT_MINUTES

    jobs: list[Job] = []
    for task in tasks:
        if task.status != "open" or task.deadline <= now:
            continue
        remaining = math.ceil(remaining_minutes(task, blocks, now) / SLOT_MINUTES)
        if remaining <= 0:
            continue
        deadline = to_ist(task.deadline)
        if deadline <= grid.end:
            jobs.append(Job(task.id, remaining, deadline, grid.slots_ending_by(deadline), task.demanding,
                            min(min_block_slots, remaining)))
        else:  # R17 / D-16: pro-rata share, due at the horizon end
            until_deadline = (deadline - now).total_seconds() / 3600
            share = min(remaining, math.ceil(remaining * horizon_hours / until_deadline - 1e-9))
            if share > 0:
                jobs.append(Job(task.id, share, grid.end, grid.n, task.demanding,
                                min(min_block_slots, share), share=True))

    used_min: dict = defaultdict(int)
    for b in blocks:
        if b.start < now:
            used_min[to_ist(b.start).date()] += b.done_minutes(now)
    day_cap = {day: max(0, (prefs.max_work_per_day_min - used_min.get(day, 0)) // SLOT_MINUTES)
               for day in grid.days}
    return Problem(now=now, prefs=prefs, events=list(events), grid=grid, jobs=jobs,
                   day_cap=day_cap, day_used_min=dict(used_min), busy=in_progress)


def _plan_from(problem: Problem, assignment: dict[str, list[int]], kind, status: str, version: int,
               seconds: float, fallback: bool = False) -> tuple[Plan, ValidationResult]:
    blocks = blocks_from_assignment(problem, assignment, version)
    check = validate(problem, blocks, kind)
    if not check.ok:
        raise PlanValidationError(check.failures)
    plan = Plan(blocks=blocks, kind=kind, status=status, fallback=fallback,
                unscheduled_min=check.unscheduled_min, deadline_misses=check.deadline_misses,
                short_blocks=check.short_blocks,
                beyond_horizon={j.task_id for j in problem.jobs if j.share},
                solve_seconds=seconds, optimal=status == "OPTIMAL")
    return plan, check


def make_plan(problem: Problem, *, solve_fn=None, diagnose_fn=None,
              time_limit: float = SOLVER_TIME_LIMIT_S, workers: int = SOLVER_WORKERS,
              plan_version: int = 0, previous_blocks: list[Block] | None = None) -> PlanOutcome:
    """Strict solve; if proven infeasible, diagnose; if the solver runs out of time, greedy (R19)."""
    solve_fn = solve_fn or solver_mod.solve  # looked up at call time, so tests can stub it
    started = clock.perf_counter()
    hint = hint_plan(problem)
    previous = None
    if previous_blocks:  # R64: prefer keeping the slots of the previous plan
        previous = defaultdict(set)
        for b in previous_blocks:
            if b.start >= problem.grid.start and b.end <= problem.grid.end:
                first = problem.grid.index_of(to_ist(b.start))
                previous[b.task_id].update(range(first, first + b.minutes // SLOT_MINUTES))
    kwargs = {"previous": dict(previous)} if previous else {}
    result = solve_fn(problem, "strict", time_limit=time_limit, workers=workers, hint=hint, **kwargs)
    elapsed = clock.perf_counter() - started

    if result.feasible:
        plan, check = _plan_from(problem, result.assignment, "optimizer", result.status, plan_version, elapsed)
        return PlanOutcome(plan, None, check, problem)

    if result.status == "INFEASIBLE":
        if diagnose_fn is None:
            from autoplanner.diagnose import diagnose as diagnose_fn
        diagnosis = diagnose_fn(problem, solve_fn=solve_fn, time_limit=time_limit, workers=workers,
                                plan_version=plan_version, hint=hint)
        check = validate(problem, diagnosis.best_effort.blocks, diagnosis.best_effort.kind)
        if not check.ok:
            raise PlanValidationError(check.failures)
        diagnosis.best_effort.solve_seconds = clock.perf_counter() - started
        return PlanOutcome(diagnosis.best_effort, diagnosis, check, problem)

    # UNKNOWN / MODEL_INVALID: show the quick greedy plan (R19).
    plan, check = _plan_from(problem, greedy_plan(problem), "greedy", "GREEDY", plan_version,
                             clock.perf_counter() - started, fallback=True)
    return PlanOutcome(plan, None, check, problem)


# ---------- service: load -> plan -> persist (R12, R35, R62) ----------

def input_hash(state: PlannerState) -> str:
    """Hash of everything that affects the plan. Future planned blocks are outputs, not inputs."""
    payload = {
        "prefs": state.prefs.to_dict(),
        "events": sorted([e.id, e.title, e.kind, str(e.start_time), str(e.end_time), str(e.on_date),
                          list(e.weekdays or ()), str(e.until_date)] for e in state.events),
        "tasks": sorted([t.id, t.est_hours, t.deadline.isoformat(), t.demanding, t.status]
                        for t in state.tasks),
        "blocks": sorted([b.id, b.status, b.actual_minutes, b.start.isoformat(), b.end.isoformat()]
                         for b in state.blocks if b.status != "planned"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def plan_meta(outcome: PlanOutcome, digest: str, version: int, now: datetime) -> dict:
    plan, diagnosis = outcome.plan, outcome.diagnosis
    meta = {
        "input_hash": digest, "plan_version": version, "planned_at": now.isoformat(),
        "kind": plan.kind, "status": plan.status, "fallback": plan.fallback,
        "unscheduled_min": plan.unscheduled_min, "deadline_misses": plan.deadline_misses,
        "short_blocks": plan.short_blocks, "beyond_horizon": sorted(plan.beyond_horizon),
        "solve_seconds": round(plan.solve_seconds, 3), "optimal": plan.optimal, "diagnosis": None,
    }
    if diagnosis is not None:
        meta["diagnosis"] = {
            "shortfall_min": diagnosis.shortfall_min,
            "extend": [[o.task_id, o.new_deadline.isoformat()] for o in diagnosis.extend_options],
            "cut": diagnosis.cut_option, "no_single_extension": diagnosis.no_single_extension,
            "cut_short": diagnosis.cut_short,
        }
    return meta


@dataclass
class PlanView:
    """What the UI shows: the stored state plus a description of its plan."""

    state: PlannerState
    now: datetime
    horizon_end: datetime

    @property
    def meta(self) -> dict:
        return self.state.meta

    @property
    def future_blocks(self) -> list[Block]:
        return sorted((b for b in self.state.blocks if b.status == "planned" and b.start >= self.now),
                      key=lambda b: b.start)

    @property
    def diagnosis(self) -> dict | None:
        return self.meta.get("diagnosis")

    def remaining_min(self, task: Task) -> int:
        return remaining_minutes(task, self.state.blocks, self.now)

    def ready_to_complete(self) -> list[Task]:
        """R26: open tasks with no work left."""
        return [t for t in self.state.tasks if t.status == "open" and self.remaining_min(t) == 0]


class PlannerService:
    """All reads and changes for one planner go through here."""

    def __init__(self, repo, planner_id: str, *, clock=None, solve_fn=None,
                 time_limit: float = SOLVER_TIME_LIMIT_S, workers: int = SOLVER_WORKERS):
        self.repo, self.planner_id = repo, planner_id
        self.clock = clock or (lambda: datetime.now(TZ))
        self.solve_fn, self.time_limit, self.workers = solve_fn, time_limit, workers

    def now(self) -> datetime:
        return to_ist(self.clock())

    def view(self) -> PlanView:
        """The current plan; re-solves only when an input changed (R62)."""
        state = self.repo.load(self.planner_id)
        now = self.now()
        refreshed = refresh_overdue(state.tasks, state.blocks, now)
        current = replace(state, tasks=refreshed)
        if refreshed != state.tasks or state.meta.get("input_hash") != input_hash(current):
            return self._commit(state, current, now)
        return PlanView(state, now, horizon_end(now, state.prefs.horizon_days))

    def change(self, mutate: Callable[[PlannerState, datetime], PlannerState]) -> PlanView:
        """Apply a change, plan it, and only then persist both (R12). Errors leave state as it was (R35)."""
        state = self.repo.load(self.planner_id)
        now = self.now()
        new = mutate(copy.deepcopy(state), now)
        new = replace(new, tasks=refresh_overdue(new.tasks, new.blocks, now))
        return self._commit(state, new, now)

    def replan(self) -> PlanView:
        return self.change(lambda s, now: replace(s, meta={**s.meta, "input_hash": None}))

    def mark_done(self, block_id: str, actual_minutes: int | None = None) -> PlanView:
        return self.change(lambda s, now: mark_done(s, now, block_id, actual_minutes))

    def mark_not_done(self, block_id: str, minutes_completed: int = 0) -> PlanView:
        return self.change(lambda s, now: mark_not_done(s, now, block_id, minutes_completed))

    def complete_task(self, task_id: str, actual_hours: float, confirm_unconfirmed: bool = False) -> PlanView:
        return self.change(lambda s, now: complete_task(s, now, task_id, actual_hours, confirm_unconfirmed))

    def extend_deadline(self, task_id: str, new_deadline: datetime) -> PlanView:
        return self.change(lambda s, now: extend_deadline(s, now, task_id, new_deadline))

    def cut_hours(self, cuts: dict[str, int]) -> PlanView:
        return self.change(lambda s, now: cut_hours(s, now, cuts))

    def cant_do(self, block_id: str) -> PlanView:
        return self.change(lambda s, now: cant_do(s, now, block_id))

    def _commit(self, old: PlannerState, new: PlannerState, now: datetime) -> PlanView:
        problem = build_problem(now, new.prefs, new.events, new.tasks, new.blocks)
        version = int(old.meta.get("plan_version", 0)) + 1
        previous = [b for b in old.blocks if b.status == "planned" and b.start >= now]
        outcome = make_plan(problem, solve_fn=self.solve_fn, time_limit=self.time_limit,
                            workers=self.workers, plan_version=version, previous_blocks=previous)
        kept = [b for b in new.blocks if not (b.status == "planned" and b.start >= now)]
        final = replace(new, blocks=kept + outcome.plan.blocks,
                        meta=plan_meta(outcome, input_hash(new), version, now))
        save_changes(self.repo, self.planner_id, old, final)
        return PlanView(final, now, horizon_end(now, final.prefs.horizon_days))


# ---------- feedback and fixes: pure state changes (R23-R26, R32, R33, R36) ----------

def _swap_block(state: PlannerState, block: Block) -> PlannerState:
    return replace(state, blocks=[block if b.id == block.id else b for b in state.blocks])


def _swap_task(state: PlannerState, task: Task) -> PlannerState:
    return replace(state, tasks=[task if t.id == task.id else t for t in state.tasks])


def mark_done(state: PlannerState, now: datetime, block_id: str, actual_minutes: int | None = None) -> PlannerState:
    """R24: a started block is done, with the actual minutes (default: its planned length)."""
    block = state.block(block_id)
    if block is None or block.start > now:
        raise ValueError("only a block that has started can be marked done")
    minutes = block.minutes if actual_minutes is None else max(0, int(actual_minutes))
    return _swap_block(state, replace(block, status="done", actual_minutes=minutes))


def mark_not_done(state: PlannerState, now: datetime, block_id: str, minutes_completed: int = 0) -> PlannerState:
    """R23 / R28: a started block didn't happen; its unfinished minutes return to the task."""
    block = state.block(block_id)
    if block is None or block.start > now:
        raise ValueError("only a block that has started can be marked not done")
    done = min(max(0, int(minutes_completed)), block.minutes)
    return _swap_block(state, replace(block, status="not_done", actual_minutes=done))


def complete_task(state: PlannerState, now: datetime, task_id: str, actual_hours: float,
                  confirm_unconfirmed: bool = False) -> PlannerState:
    """R26 / R36: store the task as completed. With confirm_unconfirmed, its unconfirmed past
    blocks become done first; learning uses the task only if none stays unconfirmed (D-1)."""
    from autoplanner.learning import learning_eligible

    if confirm_unconfirmed:
        state = replace(state, blocks=[
            replace(b, status="done", actual_minutes=b.minutes)
            if b.task_id == task_id and b.status == "planned" and b.start < now else b
            for b in state.blocks])
    task = state.task(task_id)
    done = replace(task, status="completed", actual_hours=round(max(0.0, actual_hours), 2), completed_at=now,
                   learning_eligible=learning_eligible(task_id, state.blocks, now))
    return _swap_task(state, done)


def extend_deadline(state: PlannerState, now: datetime, task_id: str, new_deadline: datetime) -> PlannerState:
    """R32 / R33: a new deadline; an overdue task becomes open again."""
    if new_deadline <= now:
        raise ValueError("the new deadline must be in the future")
    task = state.task(task_id)
    return _swap_task(state, replace(task, deadline=new_deadline, status="open"))


def cut_hours(state: PlannerState, now: datetime, cuts: dict[str, int]) -> PlannerState:
    """R32: reduce estimates by the given minutes. A task cut to nothing is closed as completed
    (with no learning data), since there is no work left to plan."""
    for task_id, minutes in cuts.items():
        task = state.task(task_id)
        if task is None:
            continue
        new_hours = round(task.est_hours - minutes / 60, 1)
        if new_hours <= 0:
            task = replace(task, status="completed", actual_hours=0.0, learning_eligible=False, completed_at=now)
        else:
            task = replace(task, est_hours=new_hours)
        state = _swap_task(state, task)
    return state


def cant_do(state: PlannerState, now: datetime, block_id: str) -> PlannerState:
    """R27: a future block can't happen: block that time (one-off) and plan around it."""
    block = state.block(block_id)
    if block is None or block.start <= now:
        raise ValueError("only a future block can be skipped")
    task = state.task(block.task_id)
    start, end = to_ist(block.start), to_ist(block.end)
    busy = Event(title=f"Can't do: {task.title if task else 'block'}", kind="blocked", start_time=start.time(),
                 end_time=end.time(), on_date=start.date())
    return replace(state, events=state.events + [busy],
                   blocks=[replace(b, status="skipped") if b.id == block_id else b for b in state.blocks])
