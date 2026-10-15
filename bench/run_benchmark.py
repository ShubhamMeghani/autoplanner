"""Optimizer vs greedy EDF on the seeded suite (R54-R57).

    python -m bench.run_benchmark --seeds 10 [--time-limit 10] [--workers 4] [--out bench/results]

Writes results.csv (one row per instance x method), REPORT.md and comparison.png. The optimizer
runs in strict mode; when strict is proven infeasible it switches to minimum total lateness, and
if the solver runs out of time the app's greedy fallback is used (as R19 does in the app).
"""

from __future__ import annotations

import argparse
import csv
import os
import platform
import statistics
import sys
import time
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

from autoplanner.baseline import greedy_plan, hint_plan
from autoplanner.config import SOLVER_TIME_LIMIT_S, SOLVER_WORKERS, TZ
from autoplanner.metrics import compute_metrics
from autoplanner.planner import build_problem
from autoplanner.solver import blocks_from_assignment, solve
from autoplanner.validate import validate
from bench.generate import RHOS, SIZES, Instance, suite

FIELDS = ["instance", "tasks", "horizon_days", "rho_target", "rho", "seed", "method", "status", "mode",
          "deadlines_met", "tasks_total", "total_lateness_h", "focus_violations", "short_blocks",
          "preference_violations", "solve_s", "proven_goals", "total_goals", "validation_failures"]


def run_instance(inst: Instance, time_limit: float, workers: int) -> list[dict]:
    problem = build_problem(inst.now, inst.prefs, inst.events, inst.tasks, [])
    base = {"instance": inst.name, "tasks": inst.n_tasks, "horizon_days": inst.horizon_days,
            "rho_target": inst.rho_target, "rho": inst.rho, "seed": inst.seed}

    started = time.perf_counter()
    greedy = greedy_plan(problem)
    greedy_s = time.perf_counter() - started
    rows = [_row(base, problem, "greedy", "GREEDY", "greedy", greedy, greedy_s, "greedy", 0, 0)]

    started = time.perf_counter()
    hint = hint_plan(problem)
    result = solve(problem, "strict", time_limit=time_limit, workers=workers, hint=hint)
    mode, kind = "strict", "optimizer"
    if result.status == "INFEASIBLE":
        # Start from the less late of the two plans; both are complete and feasible in lateness mode.
        start = min((hint, greedy), key=lambda a: compute_metrics(problem, a, 0).total_lateness_h)
        result = solve(problem, "lateness", time_limit=time_limit, workers=workers, hint=start)
        mode, kind = "lateness", "best_effort"
    assignment, status = result.assignment, result.status
    if not result.feasible:
        assignment, status, mode, kind = greedy, f"{result.status}->GREEDY", "fallback", "greedy"
    rows.append(_row(base, problem, "optimizer", status, mode, assignment, time.perf_counter() - started, kind,
                     result.proven_goals, result.total_goals))
    return rows


def _row(base, problem, method, status, mode, assignment, seconds, kind, proven, total) -> dict:
    metrics = compute_metrics(problem, assignment, seconds)
    check = validate(problem, blocks_from_assignment(problem, assignment), kind)
    return {**base, "method": method, "status": status, "mode": mode, "deadlines_met": metrics.deadlines_met,
            "tasks_total": metrics.tasks, "total_lateness_h": metrics.total_lateness_h,
            "focus_violations": metrics.focus_violations, "short_blocks": metrics.short_blocks,
            "preference_violations": metrics.preference_violations, "solve_s": round(seconds, 3),
            "proven_goals": proven, "total_goals": total, "validation_failures": len(check.failures)}


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    k = (len(ordered) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def summarise(rows: list[dict]) -> dict:
    """Aggregate checks for AC-5, AC-21, AC-22 and AC-23."""
    opt = [r for r in rows if r["method"] == "optimizer"]
    gre = [r for r in rows if r["method"] == "greedy"]
    strict_ok = [r for r in opt if r["mode"] == "strict"]
    total = lambda rs, key: sum(float(r[key]) for r in rs)  # noqa: E731
    times_20 = [float(r["solve_s"]) for r in opt if int(r["tasks"]) == 20]
    return {
        "validation_failures": int(total(rows, "validation_failures")),
        "strict_all_met": all(r["deadlines_met"] == r["tasks_total"] for r in strict_ok),
        "strict_count": len(strict_ok),
        "met": (total(opt, "deadlines_met"), total(gre, "deadlines_met")),
        "lateness": (total(opt, "total_lateness_h"), total(gre, "total_lateness_h")),
        "violations": (total(opt, "preference_violations"), total(gre, "preference_violations")),
        "median_20": statistics.median(times_20) if times_20 else 0.0,
        "p95_20": percentile(times_20, 0.95),
    }


def write_csv(rows: list[dict], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def environment(time_limit: float, workers: int) -> list[str]:
    return [f"- Date: {datetime.now(TZ):%Y-%m-%d %H:%M} IST",
            f"- CPU: {platform.processor() or platform.machine()} ({os.cpu_count()} logical cores), {platform.system()} {platform.release()}",
            f"- Python {platform.python_version()}, OR-Tools {version('ortools')}",
            f"- Solver time limit {time_limit:g} s, {workers} workers"]


# ---------- report ----------

SERIES = {"optimizer": ("Optimizer (CP-SAT)", "#2a78d6"), "greedy": ("Greedy EDF", "#eb6834")}
INK, MUTED_INK, GRID, SURFACE = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"


def _sum(rows: list[dict], key: str) -> float:
    return sum(float(r[key]) for r in rows)


def _pick(rows, method, **where) -> list[dict]:
    return [r for r in rows if r["method"] == method and all(str(r[k]) == str(v) for k, v in where.items())]


def write_chart(rows: list[dict], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    panels = [("Deadlines met (%)", lambda rs: 100 * _sum(rs, "deadlines_met") / max(1, _sum(rs, "tasks_total"))),
              ("Total lateness (hours)", lambda rs: _sum(rs, "total_lateness_h")),
              ("Preference violations", lambda rs: _sum(rs, "preference_violations"))]
    fig, axes = plt.subplots(1, 3, figsize=(12, 4), facecolor=SURFACE)
    width = 0.36
    for ax, (title, measure) in zip(axes, panels):
        ax.set_facecolor(SURFACE)
        for k, method in enumerate(("optimizer", "greedy")):
            label, colour = SERIES[method]
            values = [measure(_pick(rows, method, rho_target=rho)) for rho in RHOS]
            xs = [i + (k - 0.5) * width for i in range(len(RHOS))]
            bars = ax.bar(xs, values, width=width, color=colour, edgecolor=SURFACE, linewidth=2, label=label)
            ax.bar_label(bars, labels=[f"{v:.0f}" for v in values], padding=2, fontsize=8, color=MUTED_INK)
        ax.set_title(title, loc="left", fontsize=11, color=INK)
        ax.set_xticks(range(len(RHOS)), [f"ρ = {r}" for r in RHOS], color=MUTED_INK)
        ax.tick_params(axis="y", colors=MUTED_INK, labelsize=8, length=0)
        ax.tick_params(axis="x", length=0)
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
    axes[0].set_ylim(0, 110)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper right", ncol=2, frameon=False, fontsize=9, labelcolor=INK)
    fig.suptitle("Optimizer vs greedy EDF, summed over 3 sizes x 10 seeds per load level", x=0.01, ha="left",
                 fontsize=12, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def write_report(rows: list[dict], s: dict, env: list[str], out: Path) -> None:
    def verdict(ok: bool) -> str:
        return "**PASS**" if ok else "**FAIL**"

    lines = ["# AutoPlanner benchmark: optimizer vs greedy EDF", "",
             "Generated by `python -m bench.run_benchmark`. Raw rows: `results.csv`.", "", "## Environment", ""]
    lines += env
    lines += ["", "## Setup", "",
              f"- {len(rows) // 2} seeded instances: sizes {', '.join(f'{n} tasks / {d} days' for n, d in SIZES)}; "
              f"load ratio ρ ∈ {{{', '.join(map(str, RHOS))}}}; 10 seeds each (R54). Capacity counts available "
              "slots, each day capped at the daily work limit.",
              "- **Greedy EDF** exactly as R55: earliest deadline first, slot by slot, ignoring focus windows "
              "and the min block length; work may run past deadlines.",
              "- **Optimizer**: CP-SAT in strict mode (every deadline is a hard constraint). When strict mode is "
              "proven infeasible it switches to minimum total lateness, where the min block length becomes a "
              "soft goal (short blocks are counted, as for greedy; D-23). If it ever ran out of time, the app's "
              "greedy fallback would be used (the status column of `results.csv` shows it).",
              "- Metrics (R56): deadlines met; total lateness in hours (unplaced work counts as done right after "
              "the horizon); preference violations = demanding slots outside focus windows + blocks shorter "
              "than the min block length; solve time = wall clock including model building.",
              "", "## Results by size and load", "",
              "| Size | ρ | Deadlines met (opt / greedy) | Lateness h (opt / greedy) | Pref. violations (opt / greedy) |",
              "|---|---|---|---|---|"]
    for n, d in SIZES:
        for rho in RHOS:
            o, g = _pick(rows, "optimizer", tasks=n, rho_target=rho), _pick(rows, "greedy", tasks=n, rho_target=rho)
            lines.append(f"| {n} tasks / {d} days | {rho} | {_sum(o, 'deadlines_met'):.0f} / {_sum(g, 'deadlines_met'):.0f}"
                         f" of {_sum(o, 'tasks_total'):.0f} | {_sum(o, 'total_lateness_h'):.1f} / "
                         f"{_sum(g, 'total_lateness_h'):.1f} | {_sum(o, 'preference_violations'):.0f} / "
                         f"{_sum(g, 'preference_violations'):.0f} |")
    met, late, viol = s["met"], s["lateness"], s["violations"]
    lines += ["", "![Optimizer vs greedy by load level](comparison.png)", "",
              "## Totals and acceptance checks", "",
              "| Check | Result | |", "|---|---|---|",
              f"| AC-5: validation failures (both methods, each with its rule set) | {s['validation_failures']} | "
              f"{verdict(s['validation_failures'] == 0)} |",
              f"| AC-21: strict plans meet every deadline | {s['strict_count']} strict plans | "
              f"{verdict(s['strict_all_met'])} |",
              f"| AC-22: deadlines met, optimizer ≥ greedy | {met[0]:.0f} vs {met[1]:.0f} | {verdict(met[0] >= met[1])} |",
              f"| AC-22: total lateness, optimizer ≤ greedy | {late[0]:.1f} h vs {late[1]:.1f} h | "
              f"{verdict(late[0] <= late[1])} |",
              f"| AC-22: preference violations, optimizer < greedy | {viol[0]:.0f} vs {viol[1]:.0f} | "
              f"{verdict(viol[0] < viol[1])} |",
              f"| AC-23: 20 tasks / 7 days, median ≤ 2 s and p95 ≤ 5 s | median {s['median_20']:.2f} s, "
              f"p95 {s['p95_20']:.2f} s | {verdict(s['median_20'] <= 2 and s['p95_20'] <= 5)} |",
              "", "## Solve time and proven optimality", "",
              "| Size | Method | Median s | p95 s | Max s | All goals proven | Top goal proven |",
              "|---|---|---|---|---|---|---|"]
    for n, d in SIZES:
        for method in ("optimizer", "greedy"):
            rs = _pick(rows, method, tasks=n)
            times = [float(r["solve_s"]) for r in rs]
            if method == "optimizer":
                all_proven = 100 * sum(r["status"] == "OPTIMAL" for r in rs) / len(rs)
                top = 100 * sum(int(r["proven_goals"]) >= 1 for r in rs) / len(rs)
                proof = f"{all_proven:.0f} % | {top:.0f} %"
            else:
                proof = "– | –"
            lines.append(f"| {n} / {d} | {SERIES[method][0]} | {statistics.median(times):.2f} | "
                         f"{percentile(times, 0.95):.2f} | {max(times):.2f} | {proof} |")
    lines += ["", "Goals are solved one after another (R16): the deadlines or lateness first, then focus "
              "windows, fewer blocks and earlier days, each with a time cap. “Top goal proven” means the "
              "first goal (focus windows in strict mode, total lateness in lateness mode) was proven optimal.",
              ""]
    (out / "REPORT.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    write_chart(rows, out / "comparison.png")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Optimizer vs greedy EDF benchmark")
    parser.add_argument("--seeds", type=int, default=10)
    parser.add_argument("--time-limit", type=float, default=SOLVER_TIME_LIMIT_S)
    parser.add_argument("--workers", type=int, default=SOLVER_WORKERS)
    parser.add_argument("--out", default="bench/results")
    parser.add_argument("--report-only", action="store_true", help="rebuild REPORT.md and the chart from results.csv")
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.report_only:
        with (out / "results.csv").open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        write_report(rows, summarise(rows), environment(args.time_limit, args.workers), out)
        return 0

    instances = suite(args.seeds)
    rows: list[dict] = []
    for i, inst in enumerate(instances, 1):
        rows += run_instance(inst, args.time_limit, args.workers)
        opt = rows[-1]
        print(f"[{i:3}/{len(instances)}] {inst.name:28} optimizer {opt['mode']:8} {opt['status']:10} "
              f"{opt['solve_s']:6.2f}s", flush=True)
    write_csv(rows, out / "results.csv")
    write_report(rows, summarise(rows), environment(args.time_limit, args.workers), out)
    print(f"wrote {out / 'results.csv'}, {out / 'REPORT.md'}, {out / 'comparison.png'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
