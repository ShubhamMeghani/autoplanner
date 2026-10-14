"""Planning orchestration: remaining work, overdue tasks, the solver problem, and the
strict -> fallback -> validate pipeline (R14, R17, R19, R20, R25, R33)."""

from __future__ import annotations

import math
import time as clock
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime

from autoplanner import solver as solver_mod
from autoplanner.baseline import greedy_plan
from autoplanner.config import SLOT_MINUTES, SOLVER_TIME_LIMIT_S, SOLVER_WORKERS
from autoplanner.models import Block, Diagnosis, Event, Plan, Preferences, Task
from autoplanner.solver import blocks_from_assignment
from autoplanner.timegrid import Job, Problem, build_grid, to_ist
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
    grid = build_grid(now, prefs, events)
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
                   day_cap=day_cap, day_used_min=dict(used_min))


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


def make_plan(problem: Problem, *, solve_fn=solver_mod.solve, diagnose_fn=None,
              time_limit: float = SOLVER_TIME_LIMIT_S, workers: int = SOLVER_WORKERS,
              plan_version: int = 0) -> PlanOutcome:
    """Strict solve; if proven infeasible, diagnose; if the solver runs out of time, greedy (R19)."""
    started = clock.perf_counter()
    hint = greedy_plan(problem)
    result = solve_fn(problem, "strict", time_limit=time_limit, workers=workers, hint=hint)
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
    plan, check = _plan_from(problem, hint, "greedy", "GREEDY", plan_version,
                             clock.perf_counter() - started, fallback=True)
    return PlanOutcome(plan, None, check, problem)
