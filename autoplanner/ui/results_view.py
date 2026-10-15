"""Benchmark results page (R58): the latest REPORT.md and chart from bench/results/."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

RESULTS = Path(__file__).resolve().parents[2] / "bench" / "results"
CHART_LINE = "![Optimizer vs greedy by load level](comparison.png)"


def render() -> None:
    report = RESULTS / "REPORT.md"
    if not report.exists():
        st.caption("No benchmark report yet. Run `python -m bench.run_benchmark --seeds 10`.")
        return
    text = report.read_text(encoding="utf-8")
    before, _, after = text.partition(CHART_LINE)
    st.markdown(before)
    chart = RESULTS / "comparison.png"
    if chart.exists():
        st.image(str(chart), caption="Optimizer vs greedy EDF by load level")
    st.markdown(after)
