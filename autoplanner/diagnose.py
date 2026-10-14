"""Infeasibility diagnosis (R29-R31, R34). Phase 2: the best-effort plan only."""

from __future__ import annotations

from autoplanner import solver as solver_mod
from autoplanner.baseline import greedy_plan
from autoplanner.config import SLOT_MINUTES, SOLVER_TIME_LIMIT_S, SOLVER_WORKERS
from autoplanner.models import Diagnosis, Plan
from autoplanner.solver import blocks_from_assignment
from autoplanner.timegrid import Problem


def diagnose(problem: Problem, *, solve_fn=solver_mod.solve, time_limit: float = SOLVER_TIME_LIMIT_S,
             workers: int = SOLVER_WORKERS, plan_version: int = 0, hint=None, **_) -> Diagnosis:
    result = solve_fn(problem, "shortfall", time_limit=time_limit, workers=workers, hint=hint)
    if result.feasible:
        assignment, status = result.assignment, result.status
    else:
        assignment, status = (hint or greedy_plan(problem)), "GREEDY"
    shortfall = {job.task_id: (job.required - len(assignment.get(job.task_id, []))) * SLOT_MINUTES
                 for job in problem.jobs}
    plan = Plan(blocks=blocks_from_assignment(problem, assignment, plan_version),
                kind="best_effort" if status != "GREEDY" else "greedy", status=status,
                unscheduled_min={k: v for k, v in shortfall.items() if v > 0},
                beyond_horizon={j.task_id for j in problem.jobs if j.share})
    return Diagnosis(shortfall_min={k: v for k, v in shortfall.items() if v > 0},
                     extend_options=[], cut_option=None, best_effort=plan)
