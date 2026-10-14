"""Infeasibility diagnosis (R29-R31, R34).

1. Minimum shortfall: the fewest hours that can't be placed, per task, and a best-effort plan.
2. Cut option: drop exactly that shortfall, then re-solve strictly to confirm it fits.
3. Extend options: for one task at a time, relax only its deadline and minimise its finish
   time; the earliest feasible new deadline is then confirmed with a strict re-solve.
Every option shown has been verified (R30). Pro-rata shares of tasks due after the horizon
never get an extend option (R17). The whole search stops starting solves after the budget.
"""

from __future__ import annotations

import time
from dataclasses import replace

from autoplanner import solver as solver_mod
from autoplanner.baseline import greedy_plan
from autoplanner.config import (DIAGNOSIS_BUDGET_S, MAX_EXTEND_OPTIONS, SLOT, SLOT_MINUTES, SOLVER_TIME_LIMIT_S,
                                SOLVER_WORKERS)
from autoplanner.models import Diagnosis, ExtendOption, Plan
from autoplanner.solver import blocks_from_assignment
from autoplanner.timegrid import Problem

MAX_EXTEND_ATTEMPTS = 6


def with_required(problem: Problem, required: dict[str, int]) -> Problem:
    """The same problem with some jobs needing fewer slots (jobs reduced to 0 are dropped)."""
    min_block = problem.prefs.min_block_min // SLOT_MINUTES
    jobs = []
    for job in problem.jobs:
        need = required.get(job.task_id, job.required)
        if need > 0:
            jobs.append(replace(job, required=need, min_block=min(min_block, need)))
    return replace(problem, jobs=jobs)


def with_deadline(problem: Problem, task_id: str, deadline) -> Problem:
    jobs = [replace(j, deadline=deadline, deadline_slot=problem.grid.slots_ending_by(deadline))
            if j.task_id == task_id else j for j in problem.jobs]
    return replace(problem, jobs=jobs)


def diagnose(problem: Problem, *, solve_fn=None, time_limit: float = SOLVER_TIME_LIMIT_S,
             workers: int = SOLVER_WORKERS, plan_version: int = 0, hint=None,
             clock=time.monotonic, budget: float = DIAGNOSIS_BUDGET_S) -> Diagnosis:
    solve_fn = solve_fn or solver_mod.solve
    started = clock()

    def remaining() -> float:
        return budget - (clock() - started)

    def run(p: Problem, mode: str, **kw):
        return solve_fn(p, mode, time_limit=max(0.05, min(time_limit, remaining())), workers=workers, **kw)

    # 1. Minimum shortfall and the best-effort plan (R29, R31).
    result = run(problem, "shortfall", hint=hint)
    if result.feasible:
        assignment, kind, status = result.assignment, "best_effort", result.status
    else:  # could not even solve the relaxed model in time: fall back to greedy
        assignment, kind, status = (hint or greedy_plan(problem)), "greedy", "GREEDY"
    short_slots = {job.task_id: job.required - len([s for s in assignment.get(job.task_id, [])
                                                     if s < job.deadline_slot])
                   for job in problem.jobs}
    short_slots = {k: v for k, v in short_slots.items() if v > 0}
    plan = Plan(blocks=blocks_from_assignment(problem, assignment, plan_version), kind=kind, status=status,
                unscheduled_min={k: v * SLOT_MINUTES for k, v in short_slots.items()},
                beyond_horizon={j.task_id for j in problem.jobs if j.share})
    diagnosis = Diagnosis(shortfall_min={k: v * SLOT_MINUTES for k, v in short_slots.items()},
                          extend_options=[], cut_option=None, best_effort=plan)
    if not short_slots:
        return diagnosis

    # 2. Cut option, verified by a strict re-solve (R29, R30).
    if remaining() <= 0:
        diagnosis.cut_short = True
        return diagnosis
    reduced = with_required(problem, {j.task_id: j.required - short_slots.get(j.task_id, 0)
                                      for j in problem.jobs})
    if run(reduced, "strict", objective="feasibility", hint=assignment).feasible:
        diagnosis.cut_option = {k: v * SLOT_MINUTES for k, v in short_slots.items()}

    # 3. Extend options: tasks with a shortfall first (largest first), then the rest by deadline.
    in_horizon = [j for j in problem.jobs if not j.share]
    candidates = sorted((j for j in in_horizon if j.task_id in short_slots), key=lambda j: -short_slots[j.task_id])
    candidates += sorted((j for j in in_horizon if j.task_id not in short_slots), key=lambda j: j.deadline)
    for job in candidates[:MAX_EXTEND_ATTEMPTS]:
        if len(diagnosis.extend_options) >= MAX_EXTEND_OPTIONS:
            break
        if remaining() <= 0:
            diagnosis.cut_short = True
            break
        found = run(problem, "strict", relax_deadline_of=job.task_id, minimize_finish_of=job.task_id,
                    objective="feasibility")
        if not found.feasible or found.finish is None:
            continue
        new_deadline = problem.grid.start + found.finish * SLOT
        if new_deadline <= job.deadline:
            continue
        if remaining() <= 0:
            diagnosis.cut_short = True
            break
        if run(with_deadline(problem, job.task_id, new_deadline), "strict", objective="feasibility",
               hint=found.assignment).feasible:
            diagnosis.extend_options.append(ExtendOption(job.task_id, new_deadline))
    diagnosis.no_single_extension = not diagnosis.extend_options and not diagnosis.cut_short
    return diagnosis
