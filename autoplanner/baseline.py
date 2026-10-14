"""Greedy earliest-deadline-first baseline, exactly as SPEC R55 defines it."""

from __future__ import annotations

from collections import defaultdict

from autoplanner.timegrid import Problem


def greedy_plan(problem: Problem) -> dict[str, list[int]]:
    """Return task id -> slot indices.

    1. Visit the available slots in time order, skipping slots where the day's cap is reached.
    2. Assign the open job with the earliest deadline (ties: continue the current job, then
       larger remaining work, then ID), skipping a job whose current run is at the max length.
    3. Work may continue past a deadline. 4. Focus windows and the min block are ignored.
    """
    grid, jobs = problem.grid, problem.jobs
    remaining = {job.task_id: job.required for job in jobs}
    assignment: dict[str, list[int]] = {job.task_id: [] for job in jobs}
    used: dict = defaultdict(int)
    current, run = None, 0

    for s in range(grid.n):
        day = grid.day_of[s]
        if not grid.available[s] or used[day] >= problem.day_cap.get(day, 0):
            current, run = None, 0
            continue
        candidates = [
            job for job in jobs
            if remaining[job.task_id] > 0 and not (job.task_id == current and run >= problem.max_block)
        ]
        if not candidates:
            current, run = None, 0
            continue
        job = min(candidates, key=lambda jb: (jb.deadline, jb.task_id != current, -remaining[jb.task_id], jb.task_id))
        assignment[job.task_id].append(s)
        remaining[job.task_id] -= 1
        used[day] += 1
        run = run + 1 if job.task_id == current else 1
        current = job.task_id
    return assignment
