# AutoPlanner — Implementation Plan

| | |
|---|---|
| Based on | SPEC.md v0.4 (2026-10-15) |
| Date | 2026-10-15 |
| Budget | 3 days, about 32 focused hours |

**Rules**

- Every task lists the requirements (`R#`) and acceptance criteria (`AC-#`) it works toward. A task marked *(partial)* contributes to an AC that is completed later.
- Phases run in order. Phases 1–9 contain only **Must** work. Phase 10 (Should) starts only after every Must AC in [§3](#3-ac-traceability) is marked pass.
- Every phase ends with the tests green, a commit (referencing `R#` and `AC-#`), and a push. Every phase from Phase 3 on also redeploys to Streamlit Cloud.
- Real screenshots never enter the repo (C10). `.gitignore` is the first commit.

---

## 1. Phases at a glance

| Phase | Name | Day | Est. | Exit gate |
|---|---|---|---|---|
| 1 | Deployment check | 1 | 2 h | Live URL. Supabase write and read plus one Gemini call succeed on Cloud. |
| 2 | Scheduling engine, CI and keep-alive | 1 | 6 h | Solver, validator and baseline tests green in CI. Keep-alive run green. |
| 3 | Demo mode and calendar | 1 | 3 h | `?demo=1` shows a valid planned week on the live app. |
| 4 | Planner link, storage and data entry | 2 | 4 h | A planner can be created and reopened by link. Events, tasks and preferences can be edited. |
| 5 | Feedback, replanning, infeasibility and learning | 2 | 5 h | Done / not done replans live. Diagnosis options are verified. Learning factor is applied. |
| 6 | Calendar export | 2 | 1 h | The `.ics` file imports correctly into Google Calendar. |
| 7 | Task import | 3 | 6 h | Paste and screenshot import work, with fallback, Date check flags and no retention. |
| 8 | Benchmark | 3 | 3 h | `REPORT.md` is generated and AC-20–AC-23 pass. |
| 9 | Release | 3 | 2 h | Every Must AC is marked pass in §3. |
| 10 | Should items | leftover | — | AC-30–AC-35, AC-39 |

Day 1 (11 h) and Day 3 (11 h) are full. If Day 1 overruns, task 3.3 falls back to the D-6 day list (no calendar component), and polish moves to Day 2.

---

## 2. Phases

### Phase 1 — Deployment check (Day 1, ~2 h)

**Goal:** prove that the whole free-tier stack works end to end on Streamlit Community Cloud before any feature code is written. That stack is GitHub (public), Streamlit Cloud with Python 3.13, Supabase, Gemini, Tesseract, OR-Tools and `streamlit-calendar`.

| # | Task | R# | AC-# |
|---|---|---|---|
| 1.1 | Write `.gitignore` (`.streamlit/secrets.toml`, `private/`, `__pycache__/`, `.venv/`). Make it the **first commit**. | C5, C10, R65 | AC-3, AC-37 *(partial)* |
| 1.2 | Write the packaging files:<br>• `requirements.txt`, pinned: `streamlit`, `ortools`, `supabase`, `google-genai`, `pytesseract`, `pillow`, `streamlit-calendar`, `icalendar`, `pandas`, `matplotlib`, `tzdata`;<br>• `requirements-dev.txt`: `pytest`, `pytest-socket`;<br>• `pyproject.toml`;<br>• `packages.txt`: `tesseract-ocr`, `tesseract-ocr-eng`. | R60, R61 | AC-25 *(partial)* |
| 1.3 | Write `.streamlit/config.toml`, and `.streamlit/secrets.toml.example` with placeholders for `SUPABASE_URL`, `SUPABASE_KEY`, `GEMINI_API_KEY` and `GEMINI_MODEL`. | R5 | AC-3 *(partial)* |
| 1.4 | Set up Supabase:<br>• Create the project.<br>• Write `db/schema.sql` with **all five tables** (`planners`, `events`, `tasks`, `blocks`, `import_log`), including the columns the spec implies: `est_hours_raw`, `est_hours`, `actual_hours`, `learning_eligible`, block `status`, `actual_minutes`.<br>• Enable RLS on every table, with no `anon` policies.<br>• Apply the schema. | R6, R36 | AC-40 *(partial)* |
| 1.5 | Write a **temporary smoke page** in `streamlit_app.py`. It has four sections:<br>• **Environment:** Python version, OR-Tools version plus a 3-variable CP-SAT solve, Tesseract version (`pytesseract.get_tesseract_version()`), and the current time in IST.<br>• **Calendar:** `streamlit-calendar` renders one event, and clicking it echoes the event ID (D-6).<br>• **Supabase check** (button): insert a `planners` row with a `secrets.token_urlsafe(32)` ID, read it back, delete it, and show "OK" plus the milliseconds. The ID is never shown or logged.<br>• **Gemini check** (button): one `generate_content` call with a tiny inline PNG made with Pillow and a JSON response schema. Show the parsed JSON plus the milliseconds.<br>Each check shows a plain-language error when it fails. The checks run only when their button is clicked, so page loads don't use Gemini quota. | R2 (ID generation), R5, R6, R18, R35, R40, R41, R59, R61 | AC-25 *(partial)* |
| 1.6 | Publish:<br>• Create the **public** GitHub repo and turn on secret-scanning push protection.<br>• Push.<br>• Deploy on Streamlit Community Cloud with Python 3.13 selected, and paste the secrets into the app settings. | C5, C10, R61 | AC-3 *(partial)* |
| 1.7 | On the live URL, run every check. Record the versions, latencies and Gemini model ID in [§6 Phase 1 log](#6-phase-1-log). If `streamlit-calendar` fails, switch now to the D-6 fallback. | R61 | AC-25 *(partial)* |

**Exit:** the live URL shows Environment ✔, Calendar ✔, Supabase ✔ and Gemini ✔, and `git log -p` has no secret patterns.

### Phase 2 — Scheduling engine, CI and keep-alive (Day 1, ~6 h)

| # | Task | R# | AC-# |
|---|---|---|---|
| 2.1 | `autoplanner/config.py`: the IST zone, the 30-minute slot, the type table, the preference defaults, the solver limit and workers, and a secret accessor (secrets are never logged). | R5, R18, R59 | — |
| 2.2 | `autoplanner/models.py`: dataclasses for Event, Task, Preferences, Block (including status and `confirmed`), Plan (including a `fallback` flag and per-task unscheduled hours) and Diagnosis. | R14, R19, R25 | — |
| 2.3 | `autoplanner/timegrid.py`:<br>• the slot grid from "now", rounded up;<br>• one-off and weekly events;<br>• an availability mask covering the day window, events and blocked times;<br>• grid snapping that returns a "snapped" notice;<br>• a day index for daily caps.<br>Tests: `tests/test_timegrid.py`. | R9, R14.1, R59 | AC-26 |
| 2.4 | `autoplanner/validate.py`: an independent checker with the R20 rule sets (D-12):<br>• **base** (every plan): R14.1 and R14.2;<br>• **optimizer**: base plus R14.3–R14.6;<br>• **greedy / best-effort**: base plus R14.4 and R14.6, with deadline misses, short blocks and unscheduled hours returned as counts.<br>It returns the failures and the counts separately. Tests: `tests/test_validate.py`. | R14, R20 | AC-5 *(partial)* |
| 2.5 | `autoplanner/solver.py`, **strict mode**:<br>• A Boolean x[t,s] only for available slots before each task's deadline.<br>• At most one task per slot.<br>• Each task gets exactly its required work.<br>• Max run length enforced with sliding windows; min block length enforced with start indicators.<br>• Daily cap, counting work already done earlier that day (D-15).<br>• A task due after the horizon requires its pro-rata share ⌈remaining × horizon ÷ time to deadline⌉, due at the horizon end, ranked like any other work (D-16).<br>• Lexicographic weights in the order: focus slots, block count, sum of end slots.<br>• Time limit, workers, and the greedy plan passed as a solution hint.<br>Tests: `tests/test_solver.py`. | R14–R18 | AC-6 *(fixture)*, AC-7, AC-8, AC-27 *(first two cases)* |
| 2.6 | `autoplanner/baseline.py`: the greedy EDF baseline, exactly as R55 defines it. Tests: `tests/test_baseline.py`. | R55 | AC-5 *(partial)* |
| 2.7 | `autoplanner/planner.py`:<br>• remaining work, where done and unconfirmed blocks count as done;<br>• overdue detection;<br>• the pipeline: strict solve, then greedy fallback on `UNKNOWN` (which carries deadline-miss and short-block counts), then validation with the plan type's rule set, then the plan;<br>• an input hash for R62.<br>Tests: `tests/test_planner_replan.py` (first part). | R17, R19, R20, R25, R33, R62 | AC-11, AC-12 |
| 2.8 | `autoplanner/metrics.py`: deadlines met, total lateness, preference violations and solve time, as R56 defines them. | R56 | AC-20–AC-22 *(prep)* |
| 2.9 | `tests/conftest.py`: a fixed "now" (Wed 2026-10-14 10:00 IST), network blocked with `pytest-socket`, and a Gemini mock factory. | R60 | AC-24 *(partial)* |
| 2.10 | `.github/workflows/ci.yml`: Python 3.13, `apt install tesseract-ocr`, the pip installs, then `pytest`. | R60, R67 | AC-38 *(partial)* |
| 2.11 | `.github/workflows/supabase-keepalive.yml`: cron `0 3 */3 * *` plus `workflow_dispatch`. Add the repo secrets `SUPABASE_URL` and `SUPABASE_KEY`, then trigger one manual run. The run must not print the response body. | R63 | AC-28 |
| 2.12 | **Owner session (about 30 min):** put the 3 real screenshots into `private/teams/` and write `private/teams/labels.json` together. Confirm that `git status` shows nothing new. | R65, D-3 | AC-17 *(prep)*, AC-37 *(partial)* |

**Exit:** CI is green on `main`, the keep-alive manual run is green, and `pytest` passes locally offline.

### Phase 3 — Demo mode and calendar (Day 1, ~3 h)

| # | Task | R# | AC-# |
|---|---|---|---|
| 3.1 | `autoplanner/demo.py`: data relative to today with:<br>• ≥ 8 classes and labs;<br>• ≥ 8 tasks, ≥ 3 of them demanding and ≥ 1 longer than the max block;<br>• ≥ 1 blocked time;<br>• ≥ 3 learning-eligible completed tasks.<br>Tests: `tests/test_demo.py` checks these invariants, and that the demo plan is strict-feasible and validator-clean. | R51 | AC-4 *(partial)*, AC-5 *(demo)*, AC-6 |
| 3.2 | `streamlit_app.py`: replace the smoke page with routing to the landing page (Create / Try demo), `?demo=1`, and `?p=` (a stub until Phase 4). | R1, R52 | AC-4 *(partial)* |
| 3.3 | `autoplanner/ui/calendar_view.py`:<br>• week and day views over the whole horizon;<br>• colours by course;<br>• a marker on demanding blocks;<br>• an "unconfirmed" badge;<br>• a click opens an action panel (actions are wired in Phase 5).<br>Tests: `tests/test_app.py` (`AppTest`): week and day views, navigation to the last horizon day, and each kind of item present. | R21, R25 | AC-4 *(partial)*, AC-44 |
| 3.4 | Cache the plan in session state, keyed by the input hash, so that reruns don't solve again. | R62 | AC-9 *(prep)* |
| 3.5 | Demo session: a `MemoryRepo` (the full version comes in 4.1), the "Demo — changes are not saved" banner, and "Reset demo". Make sure no database client is created in demo mode. | R7, R52 | AC-4 *(partial)* |
| 3.6 | Redeploy. Time the demo load on the **live app** (D-17), and check that a local run with an empty secrets file loads the demo with no exception. | R61 | AC-4 |

**Exit:** the live `?demo=1` shows ≥ 8 fixed events and ≥ 8 task blocks in under 10 s, and AC-44 passes.

### Phase 4 — Planner link, storage and data entry (Day 2, ~4 h)

| # | Task | R# | AC-# |
|---|---|---|---|
| 4.1 | `autoplanner/storage.py`:<br>• a `Repository` interface, with `MemoryRepo` and `SupabaseRepo` implementations;<br>• every query filtered by `planner_id`;<br>• ID generation and validation against `^[A-Za-z0-9_-]{43}$`.<br>Tests: `tests/test_storage_memory.py` (the repository contract, A/B planner isolation, and 1,000 distinct IDs). Also run a manual `curl` check with the **anon** key: every table returns 0 rows and an insert is rejected. | R2–R6 | AC-1, AC-2, AC-40 |
| 4.2 | Create-planner flow: the link, the copy button and the warning. Load by `?p=`. Show an identical "Planner not found" page for malformed and unknown IDs, and never create a planner there. | R1–R4 | AC-1, AC-2 |
| 4.3 | When Supabase is unavailable, show the R7 message and keep demo mode working. | R7 | AC-4 |
| 4.4 | `autoplanner/ui/tasks_view.py`:<br>• the event and blocked-time form (one-off or weekly), with the snapping notice;<br>• the task form with validation and the demanding default;<br>• the edit and delete tables;<br>• a replan after every change.<br>The validation logic is kept as pure functions. Tests: `tests/test_inputs.py`. | R9–R12 | AC-26, AC-41, AC-42 |
| 4.5 | `autoplanner/ui/settings_view.py`: the preferences form, with the R13 rejections and focus-window clipping. Tests: `tests/test_inputs.py`. | R13 | AC-43 |
| 4.6 | Hygiene:<br>• a top-level error wrapper that shows plain messages and keeps the previous state;<br>• a log filter so no secrets or planner IDs reach the logs.<br>Tests: `tests/test_app.py` stubs the solver, the storage and Gemini in turn to raise, then checks for a plain message, no "Traceback", and unchanged state. | R5, R35 | AC-3 *(partial)*, AC-47 |

**Exit:** AC-1, AC-2 and AC-40–AC-43 pass, and AC-47 passes in CI.

### Phase 5 — Feedback, replanning, infeasibility and learning (Day 2, ~5 h)

| # | Task | R# | AC-# |
|---|---|---|---|
| 5.1 | Block actions:<br>• **done**, with optional actual minutes;<br>• **not done**, for blocks that have started.<br>Save the feedback and replan from the current slot, with past and done blocks frozen. Tests are in `test_planner_replan.py` and `test_app.py`: 75 minutes stored, the planned length as the default, and the badge cleared. | R23, R24 | AC-9, AC-45 |
| 5.2 | Mark-complete prompt: list the task's unconfirmed blocks with "Confirm these as done", and show the editable actual total. | R25, R26 | AC-13 |
| 5.3 | Add two more solver modes:<br>• **minimum shortfall**: a per-task slack variable, minimising the total;<br>• **minimum lateness**: work is allowed after the deadline, and Σ lateness is minimised. | R29, R31, R56 | AC-10, AC-21 *(prep)* |
| 5.4 | `autoplanner/diagnose.py`:<br>• H and the shortfall of each task;<br>• for each candidate task, one solve that relaxes only that task's deadline and minimises its finish time, then a strict re-solve to verify;<br>• a verified cut option;<br>• no extend option for pro-rata shares of tasks due after the horizon (only cut);<br>• a 15 s overall budget, checked against an injectable clock before each solve, with partial results and `cut_short`.<br>Tests: `tests/test_diagnose.py`, on a fixture that is exactly 3.0 h over, plus a fake-clock test where each solve takes 4 s. | R17, R29, R30, R34 | AC-10, AC-27 *(third case)*, AC-46 |
| 5.5 | Infeasibility UI: the banner, the best-effort plan with unscheduled hours, and Apply buttons. Overdue UI: Extend / Mark complete. | R31–R33 | AC-10, AC-12 |
| 5.6 | `autoplanner/learning.py`:<br>• eligibility (confirmed blocks only);<br>• the factor formula, clamped;<br>• rounding to the nearest 0.5, ties up.<br>Hook it into every task-creation path, with the reason text, and store both the raw and the used estimate. Tests: `tests/test_learning.py`. | R36–R38 | AC-13 |
| 5.7 | On the live app, mark a block not done 5 times and time each update. Record the result in §3. | R23, R62 | AC-9 |

**Exit:** AC-9, AC-10, AC-12, AC-13, AC-27, AC-45 and AC-46 pass.

### Phase 6 — Calendar export (Day 2, ~1 h)

| # | Task | R# | AC-# |
|---|---|---|---|
| 6.1 | `autoplanner/ics_export.py`: one `VEVENT` per future planned block, the `Asia/Kolkata` TZID, a stable UID `<block-id>@autoplanner`, a `PRODID`, and the deadline in the description. Tests: `tests/test_ics_export.py`, including the 21:00 IST → 15:30 UTC case and identical UIDs across two exports. | R49, R59 | AC-19 |
| 6.2 | A download button named `autoplanner-YYYY-MM-DD.ics`, with 3-step instructions. Manual check: import the file into a test Google Calendar. | R49 | AC-19 |

### Phase 7 — Task import (Day 3, ~6 h)

| # | Task | R# | AC-# |
|---|---|---|---|
| 7.1 | `autoplanner/importers/dates.py`: the resolver with the inferred / ambiguous / unresolved flags. `tests/test_dates.py` holds ≥ 25 table cases, including all the AC-14 examples. | R43 | AC-14 |
| 7.2 | `autoplanner/importers/text_parser.py`: the Teams 3-line layout and single-line entries with the separators `—`, `–`, ` - `, `\|` and tab (D-18). `tests/fixtures/paste_samples.txt` holds the inputs and expected records; tests in `tests/test_text_parser.py`. | R43, R46 | AC-18 |
| 7.3 | `tests/fixtures/make_synthetic_screenshots.py`:<br>• Pillow's built-in scalable font, so the output looks the same on Windows and Linux;<br>• a Teams-like list made from fictional data;<br>• due lines that cover every date rule against a fixed import date;<br>• the PNG text chunk `autoplanner-synthetic=1`;<br>• a `labels.json`.<br>Commit the generated `tests/fixtures/teams_synthetic/`. | R66 | AC-36 |
| 7.4 | `autoplanner/importers/gemini_vision.py`: inline image bytes, the R40 response schema, and a 20 s timeout. Dates are not interpreted. | R40 | AC-15, AC-29 |
| 7.5 | `autoplanner/importers/ocr.py`: Tesseract with preprocessing (grayscale, 2× upscale, threshold, and inversion for dark theme). | R41 | AC-16, AC-36 |
| 7.6 | `autoplanner/importers/pipeline.py`:<br>• engine selection and the fallback triggers;<br>• type inference from keywords;<br>• the default estimate × learning factor;<br>• the duplicate, completed and past-deadline unticking;<br>• ambiguous and unresolved rows sorted first;<br>• image bytes discarded after extraction.<br>Tests: `tests/test_import_pipeline.py`. | R38, R41, R42, R44, R45 | AC-15, AC-16, AC-29 |
| 7.7 | `autoplanner/ui/import_view.py`:<br>• the Gemini notice;<br>• the uploader, whose widget key resets after extraction;<br>• the "Screenshot taken on" date;<br>• a `data_editor` with the Date check column;<br>• a save gate that requires every ticked row to have a deadline. | R42, R44, R45 | AC-15 |
| 7.8 | `tests/test_synthetic_fixtures.py`:<br>• the generator gives the same output on each run;<br>• a guard that every tracked PNG under `tests/fixtures/` has the synthetic marker;<br>• Tesseract accuracy ≥ 80 % on the synthetic set. | R65, R66 | AC-36, AC-37 |
| 7.9 | `bench/eval_import.py`: defaults to `private/teams/`, accepts `--dir`, and prints the skip message when the folder is missing. The **owner runs it locally**. Only the aggregate percentages are recorded, each with its row count (D-19). | R65 | AC-17, AC-37 |

**Exit:** CI is green, including the Tesseract tests; AC-17 passes locally.

### Phase 8 — Benchmark (Day 3, ~3 h)

| # | Task | R# | AC-# |
|---|---|---|---|
| 8.1 | `bench/generate.py`: seeded instances, 3 sizes × 3 ρ, estimates scaled to the target ρ ± 0.05, total work ≤ 90 % of capacity, and "now" fixed at a Monday 08:00. | R54 | AC-20 |
| 8.2 | `bench/run_benchmark.py`:<br>• each instance is run by both methods;<br>• the optimizer falls back from strict to minimum lateness when strict is infeasible;<br>• the validator checks every plan;<br>• it writes `results.csv`, `REPORT.md` (aggregates, solve-time statistics, % optimal, environment) and `comparison.png`. | R55–R57 | AC-5, AC-20 |
| 8.3 | Run it on the dev machine and check AC-21–AC-23. If a check fails, tune the weights, the hint or the worker count, never the metrics. | R14, R16, R18, R56 | AC-21, AC-22, AC-23 |

### Phase 9 — Release (Day 3, ~2 h)

| # | Task | R# | AC-# |
|---|---|---|---|
| 9.1 | Write `README.md`:<br>• what the app is, with live and demo links;<br>• local setup and secrets;<br>• deployment;<br>• **re-enabling the keep-alive workflow** after GitHub's 60-day disable;<br>• the `private/` convention;<br>• the benchmark headline;<br>• the aggregate import accuracy only. | R63, R65 | AC-17 |
| 9.2 | Final deploy. On the live app, check AC-4. Disable Gemini through secrets and import a synthetic screenshot, which should produce Tesseract rows (AC-25). Then restore the secrets. | R41, R61 | AC-4, AC-25 |
| 9.3 | Final hygiene checks:<br>• the secret-pattern scan over `git log -p --all`;<br>• `git ls-files private/` prints nothing;<br>• `pytest` with no `secrets.toml` and no `private/`;<br>• CI is green and the Tesseract tests ran. | C5, C10, R60, R65, R67 | AC-3, AC-24, AC-37, AC-38 |
| 9.4 | Walk through every Must AC and set its status in §3. Anything that fails is fixed before Phase 10 starts. | — | all Must ACs |

### Phase 10 — Should items (leftover time, in spec order)

| # | Task | R# | AC-# |
|---|---|---|---|
| 10.1 | The "Overload the week" demo toggle | R53 | AC-33 |
| 10.2 | The plan summary table | R22 | AC-35 |
| 10.3 | The Estimate insights panel | R39 | AC-35 |
| 10.4 | "Can't do this slot" | R27 | AC-31 |
| 10.5 | Partial "minutes completed" on not done | R28 | AC-39 |
| 10.6 | The stability goal on replan | R64 | AC-34 |
| 10.7 | Including fixed events in the `.ics` file | R50 | AC-35 |
| 10.8 | The Gemini rate limit | R47 | AC-32 |
| 10.9 | "Try with a sample screenshot" (synthetic only) | R48 | AC-35 |
| 10.10 | Delete my planner | R8 | AC-30 |
| 10.11 | The Results page | R58 | AC-35 |

---

## 3. AC traceability

Every AC maps to the task that finally satisfies it. Status as of 2026-10-15, after Phase 9: ✅ = verified here (tests, benchmark or scripts); ⏳ = needs a live, CI or owner check (see the list after the table). Should ACs are updated in Phase 10.

| AC | Priority | Satisfied by | Verified how | Status |
|---|---|---|---|---|
| AC-1 | Must | 4.1, 4.2 | Unit (IDs) and live manual | ✅ pass (AppTest with in-memory storage) · ⏳ live check |
| AC-2 | Must | 4.1, 4.2 | Unit and live manual | ✅ pass |
| AC-3 | Must | 1.1, 1.3, 1.6, 4.6, 9.3 | Scan script | ✅ pass |
| AC-4 | Must | 3.1–3.6, 4.3, 9.2 | Live manual | ✅ pass locally · ⏳ live ≤ 10 s check |
| AC-5 | Must | 2.4, 2.6, 3.1, 8.2 | Unit and benchmark | ✅ pass |
| AC-6 | Must | 2.5, 3.1 | Unit | ✅ pass |
| AC-7 | Must | 2.5 | Unit | ✅ pass |
| AC-8 | Must | 2.5 | Unit | ✅ pass |
| AC-9 | Must | 3.4, 5.1, 5.7 | Unit and live timing | ✅ logic pass (unit) · ⏳ live 5-click timing |
| AC-10 | Must | 5.3, 5.4, 5.5 | Unit | ✅ pass |
| AC-11 | Must | 2.7 | Unit | ✅ pass |
| AC-12 | Must | 2.7, 5.5 | Unit | ✅ pass |
| AC-13 | Must | 5.2, 5.6 | Unit | ✅ pass |
| AC-14 | Must | 7.1 | Unit | ✅ pass |
| AC-15 | Must | 7.4, 7.6, 7.7 | Unit (mocked Gemini) | ✅ pass |
| AC-16 | Must | 7.5, 7.6 | Unit | ✅ pass |
| AC-17 | Must (local) | 2.12, 7.9, 9.1 | Owner's machine | ⏳ owner's real screenshots (tooling done; Gemini 15/15 on synthetic) |
| AC-18 | Must | 7.2 | Unit | ✅ pass |
| AC-19 | Must | 6.1, 6.2 | Unit and Google Calendar manual | ✅ pass (unit) · ⏳ manual Google Calendar import |
| AC-20 | Must | 8.1, 8.2 | Benchmark run | ✅ pass |
| AC-21 | Must | 8.3 | Benchmark run | ✅ pass |
| AC-22 | Must | 8.3 | Benchmark run | ✅ pass |
| AC-23 | Must | 8.3 | Benchmark run | ✅ pass |
| AC-24 | Must | 2.9, 9.3 | `pytest` offline | ✅ pass |
| AC-25 | Must | 1.2, 1.5, 1.7, 9.2 | Live manual | ⏳ live check after redeploy |
| AC-26 | Must | 2.3, 4.4 | Unit | ✅ pass |
| AC-27 | Must | 2.5, 5.4 | Unit | ✅ pass |
| AC-28 | Must | 2.11 | GitHub Actions run | ⏳ GitHub secrets + manual run |
| AC-29 | Must | 7.4, 7.6 | Unit | ✅ pass |
| AC-30 | Should | 10.10 | Unit and manual | ☐ |
| AC-31 | Should | 10.4 | Unit | ☐ |
| AC-32 | Should | 10.8 | Unit | ☐ |
| AC-33 | Should | 10.1 | Live manual | ☐ |
| AC-34 | Should | 10.6 | Unit | ☐ |
| AC-35 | Should | 10.2, 10.3, 10.7, 10.9, 10.11 | Live manual | ☐ |
| AC-36 | Must | 7.3, 7.5, 7.8 | CI | ✅ determinism and markers · ⏳ Tesseract accuracy runs in CI |
| AC-37 | Must | 1.1, 2.12, 7.8, 7.9, 9.3 | CI and scan | ✅ pass |
| AC-38 | Must | 2.10, 9.3 | GitHub Actions run | ⏳ CI run after push |
| AC-39 | Should | 10.5 | Unit | ☐ |
| AC-40 | Must | 1.4, 4.1 | Unit (isolation) and `curl` with the anon key | ✅ isolation (unit) · ⏳ anon-key curl check |
| AC-41 | Must | 4.4 | Unit | ✅ pass |
| AC-42 | Must | 4.4 | Unit | ✅ pass |
| AC-43 | Must | 4.5 | Unit | ✅ pass |
| AC-44 | Must | 3.3 | `AppTest` | ✅ pass |
| AC-45 | Must | 5.1 | Unit and `AppTest` | ✅ pass |
| AC-46 | Must | 5.4 | Unit (fake clock) | ✅ pass |
| AC-47 | Must | 4.6 | `AppTest` | ✅ pass |

**Coverage:** 47 of 47 ACs are mapped: 40 Must and 7 Should.

**Requirement coverage:** every requirement R1–R67 is assigned to at least one task and checked by at least one AC (SPEC v0.4, D-13).

---

## 4. Risks

| # | Risk | Impact | Mitigation | Retired in |
|---|---|---|---|---|
| K1 | A dependency has no wheel for Python 3.13 on Streamlit Cloud (`ortools`, `supabase` dependencies, `streamlit-calendar`). | The deploy is blocked. | Phase 1 installs and imports everything on Cloud before any feature work. As a last resort, use Python 3.12 (a spec change). | Phase 1 |
| K2 | `streamlit-calendar` click callbacks are unreliable, or the component is incompatible. | Calendar interaction (R21, R23) fails. | D-6 fallback: a read-only calendar plus a day list with buttons. Decided in 1.7. | Phase 1 |
| K3 | On Windows, `zoneinfo` has no tz database without the `tzdata` package. | IST conversions crash locally. | `tzdata` is in `requirements.txt` (1.2). | Phase 1 |
| K4 | The shared CPU on Streamlit Cloud makes solves slower than on the dev machine. | AC-9 (≤ 5 s) fails live. | Restrict variables to slots before each deadline, hint with the greedy plan, cache by input hash, and tune workers (1–4) on Cloud in 3.6 and 5.7. | Phase 5 |
| K5 | The minimum-lateness model for 30 tasks over 14 days hits the 10 s limit with a weak solution. | AC-22 or AC-23 fails. | The greedy hint means a solution is never worse than the greedy start. Use symmetry-free formulations and report % optimal. Tune in 8.3. | Phase 8 |
| K6 | Diagnosis needs several solves: H, up to 3 extensions, verification. | The R34 15 s cap is reached on Cloud. | One solve per extension (minimise that task's finish) instead of a binary search, with candidates ranked by shortfall. Partial results are allowed. | Phase 5 |
| K7 | Gemini's free-tier quota, model renames, or structured-output quirks. | Import degrades. | The model name lives in the `GEMINI_MODEL` secret, the Tesseract fallback always works, and Phase 1 proves the call on Cloud. | Phase 1 and 7 |
| K8 | Tesseract reads real Teams screenshots poorly (dark theme, small fonts). | AC-17 Tesseract ≥ 60 % fails. | Preprocessing (upscale, threshold, invert) and a forgiving line parser. Measure early with the real screenshots on Day 1 (2.12). | Phase 7 |
| K9 | Fonts differ between local Windows and CI Linux. | Synthetic PNGs and OCR accuracy differ between machines. | Use Pillow's built-in font only. AC-36 compares `labels.json`, not image bytes. | Phase 7 |
| K10 | A real screenshot is committed by accident. | Personal data is published (C10). | `.gitignore` is the first commit (1.1), the marker guard runs in CI (7.8), and 9.3 checks `git ls-files private/`. | Phase 1 and 7 |
| K11 | The Supabase project pauses during development, or GitHub disables the keep-alive after 60 days. | Planner links break. | Keep-alive in 2.11, the README note in 9.1, and demo mode is independent of Supabase. | Phase 2 |
| K12 | Scope: 56 Must requirements in about 32 h. | Phases overrun. | Should items are strictly last. Fallbacks are planned in advance: the D-6 calendar fallback, and fewer extend options (minimum 1) in R29. Re-plan at the end of each day. | Ongoing |
| K13 | Anyone can click "Create my planner" repeatedly on the public app. | Junk rows fill the 500 MB free tier. | Low risk at this scale, and rows are tiny. Monitor; a later fix would need a spec change. | Accepted |
| K14 | The Supabase key format (new `sb_secret_…` versus the legacy `service_role` JWT) may not work with `supabase-py`. | Storage fails. | Phase 1 verifies which format works. | Phase 1 |

---

## 5. Questions

All of the plan's questions are resolved in SPEC.md v0.4, §8:

| Plan question | Decision |
|---|---|
| Q-1 Validator vs. baseline | D-12. Base rules plus per-plan-type rule sets. Greedy and best-effort deadline misses and short blocks are reported, not failures. |
| Q-2, Q-3 Requirements without ACs | D-13. Added AC-39–AC-47. None moved to Should. |
| Q-4 `PLAN.md` not an output file | D-14. Added to SPEC §10. |
| Q-5 Daily cap and today's done work | D-15. Done work counts toward the cap. |
| Q-6 Tasks due after the horizon | D-16. A pro-rata share is required inside the horizon. |
| Q-7 Where timings are measured | D-17. On the live app. |
| Q-8 Smoke page | D-20. Removed in 3.2. |
| Q-9 Supabase write check | D-20. A throwaway `planners` row, deleted at once. |
| Q-10 Paste separators | D-18. `—`, `–`, ` - `, `\|` and tab. |
| Q-11 AC-17 granularity | D-19. Row counts are reported. |
| Q-12 Gemini model | D-20. Recorded in §6. |

New questions found during the build go here first, then into SPEC.md.

---

## 6. Phase 1 log

*Filled in during task 1.7. The local run was on 2026-10-15 (Windows 11, `.venv`). The live run was reported by the owner on 2026-10-15; all checks passed, and IST time and all 4 secrets were correct.*

| Item | Local | Live (Streamlit Cloud) |
|---|---|---|
| URL | http://localhost:8501 | the owner's `*.streamlit.app` URL (not recorded here) |
| Python | 3.13.7 | 3.13.16 ✅ |
| OR-Tools version | 9.15.6755, CP-SAT OPTIMAL (5, 4, 3) | 9.15.6755, CP-SAT OPTIMAL (5, 4, 3) ✅ |
| Tesseract version | not installed locally (expected) | 5.5.0 ✅ |
| `streamlit-calendar` click works? (D-6) | not checked: no browser connection; check live | yes: click received for `smoke-1` ✅. No D-6 fallback needed |
| Supabase write and read round trip (ms) | 586 | 2,449 ✅ |
| Supabase key type that works (K14) | new `sb_secret_…` secret key works with `supabase` 2.32.0 | same ✅ |
| Gemini model ID | `gemini-3.5-flash-lite` (see the finding below) | `gemini-3.5-flash-lite` ✅, correct row returned |
| Gemini call latency (ms) | 2,455 (one earlier run took 10,240) | 2,219 ✅ |

**Finding (risk K7), 2026-10-15:**
- The `AQ.` key works as an API key with `google-genai` 2.30.1. Listing models and text calls succeed, and there was no 401 / `ACCESS_TOKEN_TYPE_UNSUPPORTED`.
- `gemini-2.5-flash` returns 404: "no longer available to new users".
- `gemini-3.8-flash`, which Google recommends, returned **503 UNAVAILABLE for every request containing an image**, with or without a schema. Text and schema-only requests succeeded. `gemini-3.5-flash` and `gemini-flash-latest` also returned 503 for image requests.
- `gemini-3.5-flash-lite` read the test image correctly with the JSON schema, so `GEMINI_MODEL` is set to it for now.
- Recheck `gemini-3.8-flash` before Phase 7. Only the secret needs to change.
