"""CP-SAT model: strict, minimum-shortfall and minimum-lateness modes (R14-R18, R29, R56).

One Boolean x[j, s] per job and usable slot. Soft goals are combined with weights
computed per instance, so that a higher goal always dominates a lower one (R16).
"""

from __future__ import annotations

import time as clock
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from ortools.sat.python import cp_model

from autoplanner.config import SOLVER_TIME_LIMIT_S, SOLVER_WORKERS
from autoplanner.models import Block
from autoplanner.timegrid import Problem

Mode = Literal["strict", "shortfall", "lateness"]
Objective = Literal["full", "feasibility"]


@dataclass
class SolveResult:
    status: str  # OPTIMAL, FEASIBLE, INFEASIBLE, UNKNOWN or MODEL_INVALID
    assignment: dict[str, list[int]] = field(default_factory=dict)  # task id -> slot indices
    shortfall: dict[str, int] = field(default_factory=dict)  # task id -> slots not placed
    finish: int | None = None  # finish slot of `minimize_finish_of`
    seconds: float = 0.0

    @property
    def feasible(self) -> bool:
        return self.status in ("OPTIMAL", "FEASIBLE")


def solve(
    problem: Problem,
    mode: Mode = "strict",
    *,
    time_limit: float = SOLVER_TIME_LIMIT_S,
    workers: int = SOLVER_WORKERS,
    hint: dict[str, list[int]] | None = None,
    relax_deadline_of: str | None = None,
    minimize_finish_of: str | None = None,
    objective: Objective = "full",
) -> SolveResult:
    """Solve one plan.

    strict:    every job is placed in full before its deadline.
    shortfall: a job may leave slots unplaced; the total shortfall is minimised first.
    lateness:  work may run past deadlines; total lateness (in slots) is minimised first.
    relax_deadline_of / minimize_finish_of: used by diagnosis to find a task's earliest
    feasible deadline. objective="feasibility" skips the soft goals (for verification).
    """
    started = clock.perf_counter()
    grid, jobs = problem.grid, problem.jobs
    model = cp_model.CpModel()

    allowed: list[list[int]] = []
    for job in jobs:
        relaxed = mode == "lateness" or job.task_id == relax_deadline_of
        limit = grid.n if relaxed else job.deadline_slot
        allowed.append([s for s in range(limit) if grid.available[s]])

    x: dict[tuple[int, int], cp_model.IntVar] = {}
    for j, slots in enumerate(allowed):
        for s in slots:
            x[j, s] = model.new_bool_var(f"x{j}_{s}")

    by_slot: dict[int, list] = defaultdict(list)
    for (j, s), var in x.items():
        by_slot[s].append(var)
    for vars_ in by_slot.values():
        if len(vars_) > 1:
            model.add_at_most_one(vars_)

    shortfall_vars = {}
    for j, job in enumerate(jobs):
        placed = sum(x[j, s] for s in allowed[j])
        if mode == "shortfall":
            u = model.new_int_var(0, job.required, f"u{j}")
            shortfall_vars[j] = u
            model.add(placed + u == job.required)
        elif len(allowed[j]) < job.required:
            return SolveResult("INFEASIBLE", seconds=clock.perf_counter() - started)
        else:
            model.add(placed == job.required)

    # R14.4: no run of the same job longer than max_block slots.
    max_block = problem.max_block
    for j, slots in enumerate(allowed):
        for s in slots:
            window = range(s, s + max_block + 1)
            if all((j, t) in x for t in window):
                model.add(sum(x[j, t] for t in window) <= max_block)

    # Block starts (for R14.5 and the fragmentation goal).
    starts = {}
    for j, slots in enumerate(allowed):
        min_block = jobs[j].min_block
        for s in slots:
            st = model.new_bool_var(f"st{j}_{s}")
            starts[j, s] = st
            prev = x.get((j, s - 1))
            if prev is None:
                model.add(st == x[j, s])
            else:
                model.add(st >= x[j, s] - prev)
                model.add(st <= x[j, s])
                model.add(st <= 1 - prev)
            for k in range(1, min_block):  # R14.5: a block that starts here is >= min_block long
                nxt = x.get((j, s + k))
                if nxt is None:
                    model.add(st == 0)
                    break
                model.add_implication(st, nxt)

    # R14.6: daily cap, net of work already done that day.
    per_day: dict = defaultdict(list)
    for (j, s), var in x.items():
        per_day[grid.day_of[s]].append(var)
    for day, vars_ in per_day.items():
        model.add(sum(vars_) <= max(0, problem.day_cap.get(day, 0)))

    def finish_var(j: int, name: str):
        f = model.new_int_var(0, grid.n, name)
        for s in allowed[j]:
            model.add(f >= s + 1).only_enforce_if(x[j, s])
        return f

    finish_target = None
    if minimize_finish_of is not None:
        idx = next(j for j, job in enumerate(jobs) if job.task_id == minimize_finish_of)
        finish_target = finish_var(idx, "finish_target")

    primary = None
    if mode == "shortfall":
        primary = sum(shortfall_vars.values())
    elif mode == "lateness":
        lateness = []
        for j, job in enumerate(jobs):
            if job.deadline_slot >= grid.n or not allowed[j]:
                continue
            late = model.new_int_var(0, grid.n, f"late{j}")
            model.add(late >= finish_var(j, f"f{j}") - job.deadline_slot)
            lateness.append(late)
        primary = sum(lateness)
    elif finish_target is not None:
        primary = finish_target

    if objective == "full":
        day0 = grid.day_of[0] if grid.n else None
        total_req = sum(job.required for job in jobs)
        max_day = (grid.day_of[-1] - day0).days if grid.n else 0
        t3_max = total_req * max_day
        t2_max = total_req
        t1_max = sum(job.required for job in jobs if job.demanding)
        w2 = t3_max + 1
        w1 = w2 * t2_max + t3_max + 1
        w0 = w1 * t1_max + w2 * t2_max + t3_max + 1
        focus_violations = sum(var for (j, s), var in x.items() if jobs[j].demanding and not grid.focus[s])
        early = sum(var * (grid.day_of[s] - day0).days for (j, s), var in x.items())
        terms = w1 * focus_violations + w2 * sum(starts.values()) + early
        model.minimize(terms if primary is None else w0 * primary + terms)
    elif primary is not None:
        model.minimize(primary)

    if hint:
        hinted = {job.task_id: set(hint.get(job.task_id, ())) for job in jobs}
        for (j, s), var in x.items():
            model.add_hint(var, 1 if s in hinted[jobs[j].task_id] else 0)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.05, time_limit)
    solver.parameters.num_workers = workers
    solver.parameters.random_seed = 7
    status = solver.solve(model)
    result = SolveResult(solver.status_name(status), seconds=clock.perf_counter() - started)
    if result.feasible:
        for j, job in enumerate(jobs):
            result.assignment[job.task_id] = [s for s in allowed[j] if solver.value(x[j, s])]
            if mode == "shortfall":
                result.shortfall[job.task_id] = solver.value(shortfall_vars[j])
        if finish_target is not None:
            result.finish = solver.value(finish_target)
    return result


def blocks_from_assignment(problem: Problem, assignment: dict[str, list[int]], plan_version: int = 0) -> list[Block]:
    """Merge consecutive slots of the same task into blocks."""
    grid = problem.grid
    blocks: list[Block] = []
    for task_id, slots in assignment.items():
        run_start = prev = None
        for s in sorted(slots) + [None]:
            if s is not None and prev is not None and s == prev + 1:
                prev = s
                continue
            if run_start is not None:
                blocks.append(Block(task_id=task_id, start=grid.slot_start(run_start),
                                    end=grid.slot_end(prev), plan_version=plan_version))
            run_start = prev = s
    return sorted(blocks, key=lambda b: b.start)
