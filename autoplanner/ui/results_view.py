"""Benchmark results page (R58): the latest REPORT.md and chart from bench/results/."""

from __future__ import annotations

import re
from pathlib import Path

import streamlit as st

RESULTS = Path(__file__).resolve().parents[2] / "bench" / "results"
CHART_LINE = "![Optimizer vs greedy by load level](comparison.png)"


def _demote(markdown: str) -> str:
    """Shift headings down two levels, so the report sits under the page title (display only)."""
    return re.sub(r"^(#{1,4}) ", lambda m: "#" * (len(m.group(1)) + 2) + " ", markdown, flags=re.MULTILINE)


def render() -> None:
    report = RESULTS / "REPORT.md"
    if not report.exists():
        st.info("No benchmark report yet. Run `python -m bench.run_benchmark --seeds 10` to create one.", icon="📊")
        return
    text = report.read_text(encoding="utf-8")
    before, _, after = text.partition(CHART_LINE)
    with st.container(border=True):
        st.markdown(_demote(before))
        chart = RESULTS / "comparison.png"
        if chart.exists():
            st.image(str(chart), caption="Optimizer vs greedy EDF by load level")
        st.markdown(_demote(after))
