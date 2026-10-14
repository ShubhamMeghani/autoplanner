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

# The lowest-priority goal (earlier days) gets at most EARLINESS_TIME_S and stops within 10 %
# of its bound. Its lower bound is weak: on realistic weeks the plan found in 0.5 s was as good
# as the one after 10 s, but proving it took longer than the whole time limit. The goals above
# it (deadlines, focus windows, fewer blocks) are always solved to proven optimality first.
EARLINESS_GAP = 0.10
EARLINESS_TIME_S = 1.0
# Fewer blocks: usually proven in < 0.5 s, but finding the minimum took 4-5 s on a few weeks.
BLOCKS_TIME_S = 3.0
Objective = Literal["full", "feasibility"]


@dataclass
class SolveResult:
    status: str  # OPTIMAL, FEASIBLE, INFEASIBLE, UNKNOWN or MODEL_INVALID
    proven_goals: int = 0  # goals proven optimal, in priority order
    total_goals: int = 0
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
    feasible deadline. objective="feasibility" solves only the primary goal (if any) and
    skips the soft goals: used for verification and extension searches.
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

    # Valid cut: a job needs at least ceil(required / max_block) blocks. It doesn't change the
    # optimum, but it lets CP-SAT prove the fragmentation term optimal much sooner.
    if mode == "strict":
        for j, job in enumerate(jobs):
            js = [starts[j, s] for s in allowed[j]]
            if js:
                model.add(sum(js) >= -(-job.required // max_block))

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
        primary = cp_model.LinearExpr.sum(list(shortfall_vars.values()))
    elif mode == "lateness":
        lateness = []
        for j, job in enumerate(jobs):
            if job.deadline_slot >= grid.n or not allowed[j]:
                continue
            late = model.new_int_var(0, grid.n, f"late{j}")
            model.add(late >= finish_var(j, f"f{j}") - job.deadline_slot)
            lateness.append(late)
        primary = cp_model.LinearExpr.sum(lateness)
    elif finish_target is not None:
        primary = finish_target

    # R16: goals in strict priority order, solved lexicographically. Each goal is minimised,
    # then fixed at its value before the next one. One weighted sum of all three goals could
    # not be proven optimal within the time limit on realistic weeks.
    stages = [primary] if primary is not None else []
    gaps = [0.0] * len(stages)
    caps = [float("inf")] * len(stages)
    if objective == "full":
        gaps += [0.0, 0.0, EARLINESS_GAP]
        caps += [float("inf"), BLOCKS_TIME_S, EARLINESS_TIME_S]
        day0 = grid.day_of[0] if grid.n else None
        stages += [
            cp_model.LinearExpr.sum([var for (j, s), var in x.items()
                                     if jobs[j].demanding and not grid.focus[s]]),  # focus windows
            cp_model.LinearExpr.sum(list(starts.values())),  # fewer blocks
            cp_model.LinearExpr.weighted_sum(list(x.values()),  # earlier days
                                             [(grid.day_of[s] - day0).days for (j, s) in x]),
        ]

    solver = cp_model.CpSolver()
    solver.parameters.num_workers = workers
    solver.parameters.random_seed = 7
    deadline = started + max(0.05, time_limit)
    best: dict | None = None
    overall = "OPTIMAL"

    def run(hint_values: dict | None, cap: float) -> str:
        model.clear_hints()
        if hint_values is not None:
            for key, var in x.items():
                model.add_hint(var, hint_values[key])
        elif hint:
            hinted = {job.task_id: set(hint.get(job.task_id, ())) for job in jobs}
            for (j, s), var in x.items():
                model.add_hint(var, 1 if s in hinted[jobs[j].task_id] else 0)
        solver.parameters.max_time_in_seconds = min(cap, max(0.05, deadline - clock.perf_counter()))
        return solver.status_name(solver.solve(model))

    proven = 0
    for expr, gap, cap in zip(stages or [None], gaps or [0.0], caps or [float("inf")]):
        if best is not None and deadline - clock.perf_counter() < 0.05:
            overall = "FEASIBLE"
            break
        if expr is not None:
            model.minimize(expr)
        solver.parameters.relative_gap_limit = gap
        status = run(best, cap)
        if status in ("OPTIMAL", "FEASIBLE"):
            best = {key: solver.value(var) for key, var in x.items()}
            extra = {"short": {j: solver.value(u) for j, u in shortfall_vars.items()},
                     "finish": solver.value(finish_target) if finish_target is not None else None}
            if status == "FEASIBLE":
                overall = "FEASIBLE"
            else:
                proven += 1
            if expr is not None:
                model.add(expr <= round(solver.objective_value))
            if status == "FEASIBLE":
                break  # out of time for this goal; keep the best plan found so far
        elif best is None:
            return SolveResult(status, seconds=clock.perf_counter() - started)
        else:
            overall = "FEASIBLE"
            break

    result = SolveResult(overall, proven_goals=proven, total_goals=len(stages),
                         seconds=clock.perf_counter() - started)
    for j, job in enumerate(jobs):
        result.assignment[job.task_id] = [s for s in allowed[j] if best[j, s]]
        if mode == "shortfall":
            result.shortfall[job.task_id] = extra["short"][j]
    result.finish = extra["finish"]
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
