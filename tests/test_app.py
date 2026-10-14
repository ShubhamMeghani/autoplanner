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


# ---------- planner link flow (AC-1, AC-2) and error handling (AC-47) ----------

from dataclasses import replace  # noqa: E402

import pytest  # noqa: E402
from conftest import at as at_time, make_task, weekly  # noqa: E402

from autoplanner.models import Preferences  # noqa: E402
from autoplanner.storage import MemoryRepo, StorageUnavailable, is_valid_planner_id, new_planner_id, set_repo_override  # noqa: E402


def all_text(app: AppTest) -> str:
    parts = [e.value for group in (app.error, app.warning, app.info, app.success, app.markdown, app.code)
             for e in group]
    parts += [str(e.value) for e in app.exception]
    return "\n".join(str(p) for p in parts)


def param(app: AppTest, name: str) -> str:
    value = app.query_params[name]
    return value[0] if isinstance(value, list) else value


@pytest.fixture
def memory_repo():
    repo = MemoryRepo()
    set_repo_override(repo)
    yield repo
    set_repo_override(None)


def test_create_planner_then_reopen_by_link_ac1(memory_repo):
    app = AppTest.from_file(APP, default_timeout=60).run()
    app.button[1].click().run()  # "Create my planner"
    planner_id = param(app, "p")
    assert is_valid_planner_id(planner_id) and memory_repo.planner_exists(planner_id)
    assert "Anyone with this link can view and edit your planner" in all_text(app)

    service = PlannerService(memory_repo, planner_id)
    task = make_task("Lab report 4", 2, service.now() + (at_time(2, 23, 59) - NOW))
    service.change(lambda s, now: replace(s, tasks=[task], events=[weekly("DSA", (0, 2), "10:00", "11:00")]))

    reopened = AppTest.from_file(APP, default_timeout=60)
    reopened.query_params["p"] = planner_id
    reopened.run()
    assert not reopened.exception
    assert "Lab report 4" in reopened.dataframe[0].value["Task"].tolist()
    assert "DSA" in all_text(reopened)


def test_unknown_and_malformed_ids_show_the_same_not_found_ac2(memory_repo):
    before = len(memory_repo._planners)
    messages = []
    for planner_id in ("doesnotexist", new_planner_id()):
        app = AppTest.from_file(APP, default_timeout=60)
        app.query_params["p"] = planner_id
        app.run()
        messages.append([e.value for e in app.error])
    assert messages[0] == messages[1] == ["Planner not found. Check the link, or start fresh below."]
    assert len(memory_repo._planners) == before


def test_storage_unavailable_shows_a_plain_message_r7():
    set_repo_override(None)
    app = AppTest.from_file(APP, default_timeout=60)
    app.query_params["p"] = new_planner_id()
    app.run()  # CI has no secrets; locally pytest-socket blocks the connection. Both: unavailable.
    assert not app.exception
    assert "Storage is unavailable right now" in all_text(app)


def demo_app() -> AppTest:
    app = AppTest.from_file(APP, default_timeout=90)
    app.query_params["demo"] = "1"
    return app.run()


def test_solver_error_keeps_the_previous_plan_ac47(monkeypatch):
    app = demo_app()
    repo = app.session_state["demo_repo"]
    before = repo.load(DEMO_PLANNER_ID)

    def broken(*args, **kwargs):
        raise RuntimeError("solver exploded")

    monkeypatch.setattr("autoplanner.solver.solve", broken)
    app.button(key="replan").click().run()
    text = all_text(app)
    assert "Something went wrong while planning. Nothing was changed" in text
    assert "Traceback" not in text and not app.exception
    after = repo.load(DEMO_PLANNER_ID)
    assert after.tasks == before.tasks and after.blocks == before.blocks and after.meta == before.meta


def test_storage_error_keeps_the_previous_state_ac47(monkeypatch):
    app = demo_app()
    repo = app.session_state["demo_repo"]
    before = repo.load(DEMO_PLANNER_ID)

    def down(*args, **kwargs):
        raise StorageUnavailable("connection refused")

    for name in ("upsert_events", "upsert_tasks", "upsert_blocks", "delete_events", "delete_tasks",
                 "delete_blocks", "save_prefs"):
        monkeypatch.setattr(repo, name, down)
    app.button(key="replan").click().run()
    text = all_text(app)
    assert "storage is unavailable right now. Nothing was changed" in text
    assert "Traceback" not in text and not app.exception
    after = repo.load(DEMO_PLANNER_ID)
    assert after.tasks == before.tasks and after.blocks == before.blocks and after.meta == before.meta
