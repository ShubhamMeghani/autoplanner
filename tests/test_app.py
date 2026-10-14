"""App-level tests: calendar view model (AC-44) and Streamlit AppTest smoke runs."""

from pathlib import Path

from conftest import NOW
from streamlit.testing.v1 import AppTest

from autoplanner.demo import DEMO_PLANNER_ID, demo_repo
from autoplanner.planner import PlannerService
from autoplanner.ui.calendar_view import calendar_events, calendar_options

APP = str(Path(__file__).resolve().parents[1] / "streamlit_app.py")


def demo_view():
    return PlannerService(demo_repo(NOW), DEMO_PLANNER_ID, clock=lambda: NOW).view()


def test_calendar_offers_week_and_day_views_up_to_the_horizon_ac44():
    view = demo_view()
    options = calendar_options(view)
    assert "timeGridWeek" in options["headerToolbar"]["right"]
    assert "timeGridDay" in options["headerToolbar"]["right"]
    assert options["validRange"]["end"] == view.horizon_end.date().isoformat()
    last_day = (view.horizon_end.date().toordinal() - NOW.date().toordinal())
    assert last_day == view.state.prefs.horizon_days  # navigation reaches the last horizon day


def test_calendar_shows_every_kind_of_item_ac44():
    events = calendar_events(demo_view())
    kinds = {e["extendedProps"]["kind"] for e in events}
    assert kinds == {"event", "blocked", "block"}
    assert all("T" in e["start"] and "+" not in e["start"] for e in events)  # IST wall clock


def test_landing_page_renders():
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert [b.label for b in at.button] == ["Try the demo", "Create my planner"]


def test_demo_page_renders_without_errors():
    at = AppTest.from_file(APP, default_timeout=60)
    at.query_params["demo"] = "1"
    at.run()
    assert not at.exception and not at.error
    assert any("Demo" in i.value for i in at.info)
