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


def hint_plan(problem: Problem) -> dict[str, list[int]]:
    """A starting point for CP-SAT (not the R55 baseline): earliest deadline first, but placed in
    whole runs that respect the min and max block length and the daily cap. Work may run past a
    deadline. The R55 greedy plan ignores the min block, so CP-SAT had to repair it and often
    started far from a good plan."""
    grid, jobs = problem.grid, problem.jobs
    remaining = {job.task_id: job.required for job in jobs}
    assignment: dict[str, list[int]] = {job.task_id: [] for job in jobs}
    used: dict = defaultdict(int)
    last_task, last_end = None, -1
    s = 0
    while s < grid.n:
        day = grid.day_of[s]
        if not grid.available[s] or used[day] >= problem.day_cap.get(day, 0):
            s += 1
            continue

        def free_run(limit: int) -> int:
            length = 0
            while (length < limit and s + length < grid.n and grid.available[s + length]
                   and grid.day_of[s + length] == day
                   and used[day] + length < problem.day_cap.get(day, 0)):
                length += 1
            return length

        placed = False
        for job in sorted((j for j in jobs if remaining[j.task_id] > 0),
                          key=lambda j: (j.deadline, -remaining[j.task_id], j.task_id)):
            if job.task_id == last_task and s == last_end:
                continue  # a run straight after the same task's run would exceed the max block
            left = remaining[job.task_id]
            # The longest run that fits here and leaves either nothing or at least one full
            # min block for later, so no run is ever shorter than the min block.
            length = free_run(min(problem.max_block, left))
            while length > 0 and 0 < left - length < job.min_block:
                length -= 1
            if length > 0 and length >= min(job.min_block, left):
                assignment[job.task_id].extend(range(s, s + length))
                remaining[job.task_id] -= length
                used[day] += length
                last_task, last_end = job.task_id, s + length
                s += length
                placed = True
                break
        if not placed:
            s += 1
    return assignment
