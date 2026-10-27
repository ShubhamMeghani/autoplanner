# AutoPlanner — Specification

| | |
|---|---|
| Status | Draft v0.12 |
| Date | 2026-10-15 |
| Owner | Shubham Meghani |
| Build budget | 3 days |

**How to read this spec**

- Requirements use EARS patterns: `WHEN <trigger>` (event), `WHILE <state>` (state), `IF <condition>, THEN` (unwanted behaviour), `WHERE <feature>` (optional feature), or a plain `THE SYSTEM SHALL` (always true).
- Every requirement (`R#`) and acceptance criterion (`AC-#`) has a **Priority**:
  - **Must**: part of the 3-day build.
  - **Should**: built only after every Must acceptance criterion passes.
- Commits refer to `R#` and `AC-#`. IDs are never reused or renumbered.
- An acceptance criterion either passes or fails. It lists the requirements it checks.
- Building a file that is not in [§10 Output files](#10-output-files) needs a changelog entry first.

---

## 1. Goal

AutoPlanner is a free web app that plans a student's week automatically. The student enters fixed commitments, tasks with deadlines, and preferences. An optimizer (OR-Tools CP-SAT) then places work blocks in 30-minute slots. It meets every deadline, puts demanding work in the student's focus hours, splits big tasks into chunks, and respects the student's preferences. When the plan changes (a block is not done, or a new task arrives), the app replans at once. When the deadlines cannot all be met, the app says so and suggests concrete fixes. It does not fail silently.

Success means three things:

1. A first-time visitor can see a full, realistic planned week in demo mode within seconds, with no setup.
2. A student can import their Teams assignments from a screenshot, review them, and get a valid plan.
3. A reproducible benchmark shows, with numbers, that the optimizer beats a greedy earliest-deadline-first (EDF) baseline.

## 2. Users

| User | Need | Typical size |
|---|---|---|
| **Student** (primary). For example, an IISc student with classes and labs whose assignments are listed in MS Teams | Know what to work on and when. Recover quickly when the day goes off-plan. | 6–12 fixed events a week, 5–25 open tasks, 7-day horizon |
| **Visitor / evaluator** (recruiter, peer, grader) | Try the app in under a minute without signing up, and see that the scheduling is good | Demo data only |
| **Developer** (the owner) | Reproduce the benchmark, run the tests, and deploy for free | — |

## 3. Constraints

| # | Constraint |
|---|---|
| C1 | **Cost: zero.** Only free tiers: Streamlit Community Cloud, the Supabase free tier, the Gemini API free tier, GitHub Actions, and open-source libraries. |
| C2 | **Time:** the whole project, including deployment and the benchmark report, must be buildable in 3 days by one developer. Every Must item has to fit in that budget. |
| C3 | **Stack:** Python 3.13 and Streamlit, deployed on Streamlit Community Cloud. Other components: Supabase Postgres (`supabase` Python client), `ortools` CP-SAT, the Gemini API through the `google-genai` SDK, `pytesseract` with Tesseract installed through `packages.txt`, the `streamlit-calendar` component (FullCalendar), and `icalendar` for export. |
| C4 | **No login.** Each planner is reached by a private link that contains a long, random, unguessable ID (256 bits). Whoever holds the link has full access. |
| C5 | **Secrets** live only in Streamlit secrets (`.streamlit/secrets.toml` locally, the app settings on Cloud) and, for the keep-alive workflow, in GitHub Actions encrypted secrets. Secrets are never committed to git. The repo ships only `secrets.toml.example`, with placeholders. |
| C6 | **Time model:** timezone `Asia/Kolkata` (IST, which has no DST). Slots are 30 minutes long and aligned to :00/:30. The planning horizon is 1–14 days (default 7). The database stores times as `timestamptz` (UTC). Times are shown in IST. |
| C7 | **Compute:** Streamlit Community Cloud gives limited shared CPU and about 1 GB of RAM. The solver therefore has a wall-clock limit (default 10 s) and a configurable worker count (default 4). |
| C8 | **Teams data comes only from screenshots or pasted text.** The Graph API is ruled out: it was tested, and IISc requires admin consent for the assignment permissions. |
| C9 | Screenshots sent to Gemini leave the app. Inside AutoPlanner they exist only in memory during extraction and are never stored after the import. |
| C10 | **The GitHub repository is public.** Nothing personal is ever committed: no real screenshots, no labels made from them, no planner IDs, no secrets. Real screenshots live only in the git-ignored `private/` folder. Committed test images are synthetic and generated from sample data. |

## 4. Inputs and outputs

### 4.1 Inputs

| Input | Fields | Source |
|---|---|---|
| **Fixed event** | title; kind (`class` \| `lab` \| `other`); start and end time-of-day; *either* a single date *or* weekly days (Mon–Sun) with an optional end date | Manual entry, demo |
| **Blocked time** | Same shape as a fixed event, with kind `blocked` (for example gym, commute, or "not available") | Manual entry |
| **Task** | title; course (optional); type (`assignment` \| `lab_report` \| `project` \| `exam_prep` \| `reading` \| `quiz` \| `other`); estimated hours (0.5–40, step 0.5); deadline (IST date and time, default 23:59); demanding (bool, default taken from the type) | Manual entry, quick paste, screenshot import, demo |
| **Preferences** | day start (default 08:00); no work at or after (default 23:00); focus windows (default 09:00–12:00 and 18:00–21:00, the same every day); min block length (default 1 h); max block length (default 2 h, range 1–4 h); max work per day (default 8 h, a hard limit); horizon days (default 7, max 14) | Settings page |
| **Block feedback** | `done` (optionally with actual minutes); `not done` (optionally with minutes completed); `can't do this slot` (Should) | Calendar interaction |
| **Screenshot** | PNG, JPEG or WebP, ≤ 10 MB each, ≤ 5 per import, plus an "import date" (default today IST, editable) | Upload |
| **Pasted text** | Free text copied from the Teams Assignments list, or one assignment per line | Text area |

**Type table.** This table gives the defaults used when a task is created or imported.

| Type | Demanding by default | Default estimate | Title keywords used to infer the type |
|---|---|---|---|
| assignment | yes | 3 h | *(fallback)* |
| lab_report | no | 3 h | lab, experiment |
| project | yes | 6 h | project, mini-project |
| exam_prep | yes | 5 h | exam, midterm, midsem, endsem, final |
| reading | no | 1.5 h | read, reading, chapter |
| quiz | no | 1 h | quiz, test |
| other | no | 2 h | — |

### 4.2 Outputs

| Output | Description |
|---|---|
| **Weekly calendar** | Week and day views over the horizon. Shows fixed events, blocked times, and task blocks colour-coded by course, with a marker on demanding blocks and an "unconfirmed" badge on past blocks that have no feedback. Clicking a block opens done / not done actions. |
| **Plan summary** | For each task: hours scheduled, hours remaining, planned finish time, and slack before the deadline. |
| **Infeasibility report** | Shown when the deadlines cannot all be met. Gives the minimum hours that don't fit, the shortfall per task, verified "extend deadline" and "cut hours" options, and a best-effort plan. |
| **Estimate insights** | For each task type: the learned correction factor and its sample size. |
| **Import review table** | Editable rows of extracted assignments, with a "Date check" column that flags inferred and ambiguous dates. Shown before anything is saved. |
| **`.ics` file** | The planned task blocks (and, optionally, fixed events), ready to import into Google Calendar. |
| **Benchmark artifacts** | `bench/results/results.csv`, `bench/results/REPORT.md` and `bench/results/comparison.png`. |

### 4.3 Glossary

- **Slot**: a 30-minute interval aligned to :00/:30 IST.
- **Block**: a maximal run of consecutive slots assigned to the same task.
- **Remaining work**: estimated hours minus the work already done, rounded up to whole slots.
- **Confirmed block**: a block the user marked `done` or `not done`. A past block with no feedback is **unconfirmed**.
- **Available slot**: a slot inside the horizon, at or after "now", at or after day start, before "no work at/after", and not overlapping any fixed event or blocked time.
- **Feasible**: every hard constraint in R14 can be satisfied at the same time.
- **Instant**: the updated calendar renders ≤ 5 s after the user's click for a workload of ≤ 25 tasks over a 7-day horizon.
- **Load ratio ρ**: the largest value, over all deadlines *d*, of (work due by *d*) ÷ (capacity before *d*), where capacity counts available slots with each day capped at the max work per day (D-22).

## 5. Requirements (EARS)

### 5.1 Planner, link and storage

| ID | Priority | Requirement |
|---|---|---|
| R1 | Must | WHEN a visitor opens the app without a planner ID, THE SYSTEM SHALL offer two choices: "Create my planner" and "Try the demo". |
| R2 | Must | WHEN the user creates a planner, THE SYSTEM SHALL:<br>• generate the planner ID on the server with a cryptographically secure generator (`secrets.token_urlsafe(32)`: 256 bits, 43 URL-safe characters). The ID SHALL NOT be derived from the time, a counter, or user input.<br>• store an empty planner with the default preferences;<br>• show the private link `…/?p=<id>` with a copy button and the warning "Anyone with this link can view and edit your planner. Bookmark it — there is no other way back in." |
| R3 | Must | WHEN a visitor opens a link with a valid planner ID, THE SYSTEM SHALL load that planner's events, blocked times, tasks, preferences, blocks and completion history. |
| R4 | Must | IF the planner ID does not match `^[A-Za-z0-9_-]{43}$`, or matches but is unknown, THEN THE SYSTEM SHALL show the same "Planner not found" message in both cases and offer to create a planner or try the demo. It SHALL NOT create a planner under that ID. |
| R5 | Must | THE SYSTEM SHALL read the Supabase URL and key, the Gemini API key and the Gemini model name only from `st.secrets`. It SHALL NOT log, display, or write them to any file in the repository. It SHALL NOT write planner IDs to logs. |
| R6 | Must | THE SYSTEM SHALL access Supabase only from the Streamlit server, using a server-side key. Every table SHALL have row-level security enabled with no policies for the `anon` role. Every query SHALL be filtered by `planner_id`. |
| R7 | Must | IF Supabase is not configured or cannot be reached, THEN THE SYSTEM SHALL keep demo mode fully working. For planner features, it SHALL show "Storage is unavailable right now; try the demo or retry later" instead of an exception. |
| R8 | Should | WHEN the user confirms "Delete my planner", THE SYSTEM SHALL delete all rows that belong to that planner and return to the landing page. |

### 5.2 Entering events, tasks and preferences

| ID | Priority | Requirement |
|---|---|---|
| R9 | Must | WHEN the user saves a fixed event or blocked time, THE SYSTEM SHALL store it as either a one-off event or a weekly recurring one. It SHALL widen times that are not on the slot grid to the grid (start rounded down, end rounded up) and tell the user that it did so. |
| R10 | Must | WHEN the user saves a task manually, THE SYSTEM SHALL check that the title is not empty, the estimate is in 0.5–40 h, and the deadline is in the future. It SHALL default `demanding` from the type table and store the task as `open`. |
| R11 | Must | IF a task fails validation, THEN THE SYSTEM SHALL show the reason next to the field and SHALL NOT save the task. |
| R12 | Must | WHEN the user edits or deletes a task, event, blocked time or preference, THE SYSTEM SHALL save the change and replan (R13–R22) automatically. |
| R13 | Must | WHEN the user saves preferences, THE SYSTEM SHALL reject two cases: day start at or after "no work at/after", and min block length greater than max block length. Focus windows that fall outside the working day SHALL be clipped to it, with a notice. |

### 5.3 Scheduling

| ID | Priority | Requirement |
|---|---|---|
| R14 | Must | WHEN a plan is computed, THE SYSTEM SHALL build the slot grid from "now" (rounded up to the next slot, IST) to 24:00 on the last horizon day. It SHALL enforce these **hard constraints**:<br>1. Task slots are placed only in available slots.<br>2. At most one task occupies a slot.<br>3. Every task whose deadline is inside the horizon gets all of its remaining work in slots that end at or before its deadline. Every task due after the horizon gets its pro-rata share (R17) before the horizon end.<br>4. No block is longer than the max block length.<br>5. Every block is at least min(min block length, the work required in this plan) long.<br>6. Task work on any calendar day does not exceed the max work per day. This includes work already done or planned earlier that day. |
| R15 | Must | WHEN a task's remaining work is longer than the max block length, THE SYSTEM SHALL split the task into several blocks, each within the min and max block lengths. |
| R16 | Must | WHEN a plan is computed, THE SYSTEM SHALL optimise these soft goals in strict priority order, **solved one after another** (each goal is minimised, then fixed at its value before the next):<br>1. Demanding-task slots placed inside focus windows (minimise the slots outside them).<br>2. Fewer blocks (minimise fragmentation).<br>3. Earlier completion: minimise the sum, over work slots, of their day offset from today, which leaves buffer before deadlines. May stop within 10 % of its lower bound.<br>Each goal has a time cap once a plan exists (D-21): focus 0.8 s, fewer blocks 0.5 s, earlier completion 0.3 s, and minimum lateness 1.5 s in the benchmark's lateness mode. If no plan exists when a cap expires, the search continues within the R18 limit. The minimum-shortfall goal of diagnosis is never capped, so H stays exact (R29). Goals may therefore be near-optimal rather than proven optimal; the benchmark reports how often they were proven (R57). The solver is given a starting plan that respects the block-length rules. Stability on replan is a lower-priority goal; see R64. |
| R17 | Must | WHEN a task's deadline is after the horizon end, THE SYSTEM SHALL require its **pro-rata share** inside the horizon:<br>• share = ⌈remaining work × (horizon length ÷ time from now to the deadline)⌉, in whole slots, and never more than the remaining work;<br>• the share is treated as work due at the horizon end, and ranks like any other work for focus windows (R16);<br>• the rest of the task is not placed in this plan;<br>• the task SHALL be labelled "continues beyond this plan".<br>IF the share cannot fit, THEN the plan is infeasible (R29). For such a task, only the cut option applies, not an extend option. |
| R18 | Must | THE SYSTEM SHALL run CP-SAT with a wall-clock limit (default 10 s, configurable) and a configurable number of workers (default 4). |
| R19 | Must | IF CP-SAT returns neither a feasible plan nor a proof of infeasibility within the limit, THEN THE SYSTEM SHALL show the greedy EDF plan (R55) instead. A banner SHALL say "Showing a quick plan — the optimizer ran out of time." The plan's deadline misses and short blocks SHALL be shown (R20). |
| R20 | Must | WHEN any plan is produced (by the optimizer, the fallback, diagnosis, or the benchmark), THE SYSTEM SHALL check it with an independent validator before saving or displaying it. The validator applies the rule set for the plan's type:<br>• **Base rules**, for every plan: R14.1 (only available slots: no clash with fixed events, no blocked or out-of-hours time, nothing in the past) and R14.2 (no overlaps).<br>• **Optimizer plans** (strict mode): the base rules plus R14.3–R14.6.<br>• **Greedy plans** (the baseline and the R19 fallback) and **best-effort plans** (minimum shortfall, minimum lateness): the base rules plus R14.4 and R14.6. Deadline misses (R14.3), short blocks (R14.5) and unscheduled hours are counted and reported with the plan. They are not validation failures.<br>IF a plan breaks a rule in its rule set, THEN THE SYSTEM SHALL NOT save that plan. It SHALL show an error message and keep the previous plan. |
| R21 | Must | WHEN a plan is ready, THE SYSTEM SHALL display it in the calendar (week and day views) with fixed events and blocked times. The week view SHALL open 2 days before today, so recent blocks can be marked done or not done straight away. It SHALL be possible to move through the whole horizon. WHEN the user clicks a block, THE SYSTEM SHALL confirm the selection with a notice, scroll to the block's details and actions, and show them highlighted. |
| R22 | Should | WHEN a plan is ready, THE SYSTEM SHALL show the plan summary table described in §4.2. |
| R64 | Should | WHEN replanning, THE SYSTEM SHALL, as its lowest-priority soft goal (below R16's goals), minimise the number of future slots that differ from the previous plan. |

### 5.4 Feedback and replanning

| ID | Priority | Requirement |
|---|---|---|
| R23 | Must | WHEN the user marks a block that has started (start ≤ now) as **not done**, THE SYSTEM SHALL return the block's unfinished minutes to the task's remaining work. It SHALL keep every past block and every `done` block fixed, replan from the current slot, and show the new plan instantly (§4.3). |
| R24 | Must | WHEN the user marks a block **done**, THE SYSTEM SHALL record it as done (confirmed), with the actual minutes if the user gives them (default: the planned length). |
| R25 | Must | WHILE a past block has no feedback, THE SYSTEM SHALL count it as done when it computes remaining work, show it with an "unconfirmed" badge, and exclude it from learning data (R36). |
| R26 | Must | WHEN a task's remaining work reaches zero, THE SYSTEM SHALL prompt "Mark complete?". The prompt SHALL:<br>• list any unconfirmed blocks of the task, with a "Confirm these as done" option;<br>• show an editable actual total (default: the sum of the confirmed done minutes).<br>On confirmation, THE SYSTEM SHALL store the task as `completed` with the actual hours. |
| R27 | Should | WHEN the user marks a future block **can't do this slot**, THE SYSTEM SHALL add a one-off blocked time covering that block and replan. |
| R28 | Should | WHEN the user marks a block not done with "minutes completed" > 0, THE SYSTEM SHALL count those minutes as done and return only the rest. |

### 5.5 Infeasibility and overdue work

| ID | Priority | Requirement |
|---|---|---|
| R29 | Must | IF the hard model is proven infeasible, THEN THE SYSTEM SHALL show the banner "Can't fit everything before the deadlines". The banner SHALL show:<br>• **H**, the minimum total hours that cannot be scheduled (solved exactly by a model that allows per-task shortfall and minimises the total), and the shortfall of each task;<br>• up to 3 **"Extend deadline"** options. Each names a task and the earliest new deadline (on the slot grid) that makes the whole plan feasible when only that task's deadline moves;<br>• one **"Cut hours"** option: reduce the listed tasks by the listed hours, H in total. |
| R30 | Must | WHEN the system offers an extend or cut option, THE SYSTEM SHALL have re-solved the instance with that option applied and confirmed that it is feasible. Unverified options SHALL NOT be shown. IF no single-deadline extension within the horizon gives a feasible plan, THEN THE SYSTEM SHALL say so and offer only the cut option. |
| R31 | Must | WHILE the plan is infeasible, THE SYSTEM SHALL display the best-effort plan from the minimum-shortfall model, with the unscheduled hours of each task listed next to the calendar. |
| R32 | Must | WHEN the user clicks an option's "Apply" button, THE SYSTEM SHALL update the task (new deadline or reduced estimate) and replan. |
| R33 | Must | IF an open task's deadline has passed with remaining work, THEN THE SYSTEM SHALL mark the task `overdue`, leave it out of planning, and offer "Extend deadline" or "Mark complete". |
| R34 | Must | IF infeasibility diagnosis together takes longer than 15 s, THEN THE SYSTEM SHALL show the options found so far and the best-effort plan, and note that the search was cut short. |
| R35 | Must | IF any error occurs while planning or importing, THEN THE SYSTEM SHALL show a plain-language message and keep the previous state. It SHALL NOT show a stack trace to the user. |

### 5.6 Learning from actual time

| ID | Priority | Requirement |
|---|---|---|
| R36 | Must | WHEN a task is completed, THE SYSTEM SHALL store:<br>• its type and its raw estimate (the user's number before correction);<br>• its actual hours: the sum of user-confirmed done minutes plus any extra time the user enters in the R26 prompt;<br>• `learning_eligible = true` only if none of the blocks counted toward its work is unconfirmed. |
| R37 | Must | THE SYSTEM SHALL compute a correction factor for each task type from the last 10 completed tasks of that type with `learning_eligible = true` and actual hours > 0:<br>• *n* is the number of such tasks and *r* = Σ actual ÷ Σ raw estimate;<br>• factor = 1 + (n ÷ (n + 2)) × (r − 1), clamped to [0.5, 2.5];<br>• with *n* = 0 the factor is 1.0. |
| R38 | Must | WHEN a task is created from any source and its type has factor ≠ 1.0, THE SYSTEM SHALL:<br>• prefill the estimate as raw × factor, rounded to the nearest 0.5 h (ties round up);<br>• show the reason, for example "You usually take 1.3× on lab reports (3 tasks)";<br>• let the user override the value;<br>• store both the raw and the used estimate.<br>Tasks that are already open are not re-estimated. |
| R39 | Should | THE SYSTEM SHALL show an "Estimate insights" panel with the factor, n and r for each type. |

### 5.7 Adding tasks: screenshot, paste, manual

| ID | Priority | Requirement |
|---|---|---|
| R40 | Must | WHEN the user uploads Teams Assignments screenshots, THE SYSTEM SHALL send each image's bytes inline in the request to Gemini (not through the Gemini Files API), with a fixed JSON response schema. Each row has:<br>• `title`;<br>• `course`;<br>• `due_text`, copied exactly as shown (for example "Due tomorrow at 11:59 PM");<br>• `status`: `upcoming` \| `past_due` \| `completed` \| `unknown`.<br>Gemini SHALL NOT be asked to work out dates. Date resolution is done locally (R43). |
| R41 | Must | IF the Gemini key is missing, or the call fails, times out (20 s), returns invalid JSON, or returns zero rows, THEN THE SYSTEM SHALL run Tesseract OCR on the image and parse the text with the quick-paste parser (R46). It SHALL label the result "Read with Tesseract (fallback)". |
| R42 | Must | WHEN screenshot import runs, THE SYSTEM SHALL:<br>• label which engine produced each row;<br>• before the first upload, show the notice "Screenshots are sent to Google Gemini for reading and are never stored by AutoPlanner";<br>• keep images only in memory during extraction;<br>• never write images to disk, the database or logs;<br>• drop the images from session state and reset the uploader once the review table is built.<br>Only the extracted text rows are kept. |
| R43 | Must | WHEN a due text is resolved, THE SYSTEM SHALL use the import date (default today IST, editable as "Screenshot taken on") as the reference and apply these rules:<br>• `today` / `tomorrow` / `yesterday` map to that day relative to the import date.<br>• A weekday name maps to the next date with that weekday strictly after the import date. If the weekday is the import day itself, the date is one week later.<br>• A month and day without a year (`Oct 20`, `20 October`, `Mon, Oct 20`) maps to the year that puts the date closest to the import date.<br>• Explicit years are kept.<br>• 12-hour and 24-hour times are accepted. A missing time means 23:59.<br>• All results are in IST.<br>• Text that cannot be resolved gives an empty deadline.<br>Each result SHALL carry a flag:<br>• **inferred**: relative word, weekday name, year assumed, or time assumed;<br>• **ambiguous**: the weekday is the same as the import day;<br>• **unresolved**: no date could be found;<br>• *none*: the full date was explicit. |
| R44 | Must | WHEN extraction finishes (screenshot or paste), THE SYSTEM SHALL show an editable review table with these columns: include, title, course, type (inferred from keywords), estimate (type default × learning factor), deadline, **Date check**, demanding, source text, and engine. In the Date check column:<br>• inferred dates show "ⓘ" and the reason (for example "time assumed 23:59");<br>• ambiguous dates show "⚠" and the reason;<br>• unresolved dates show "✖ needs a date".<br>Rows with ambiguous or unresolved dates SHALL be listed first. THE SYSTEM SHALL NOT save anything until the user clicks "Add selected tasks". |
| R45 | Must | WHEN the review table is built, THE SYSTEM SHALL untick rows with status `completed`, rows that duplicate an existing task (same normalised title and course, with deadlines within 1 h of each other), and rows with a past deadline. It SHALL require a deadline on every ticked row before it saves. |
| R46 | Must | WHEN the user submits pasted text, THE SYSTEM SHALL parse it with a deterministic rule-based parser and show the same review table. The parser accepts the Teams list copy-paste layout (title line, course line, due line). It also accepts single-line `title <sep> due text` entries, where `<sep>` is `—`, `–`, ` - `, `\|` or a tab. |
| R47 | Should | THE SYSTEM SHALL allow at most 20 Gemini calls per planner per IST day and 10 per browser session in demo mode. Beyond the limit it SHALL use Tesseract and say so. |
| R48 | Should | WHILE in demo mode, THE SYSTEM SHALL offer a "Try with a sample screenshot" button that runs the import pipeline on one of the synthetic screenshots (R66). It SHALL never use a real one. |
| R68 | Must | WHEN the user clicks the "Paste your screenshot here (Ctrl+V)" area on the Import tab and presses Ctrl+V with an image on the clipboard, THE SYSTEM SHALL take the image from the browser's paste event (no clipboard permission needed in Chrome, Edge, Firefox or Brave) and send it through the same pipeline as an uploaded screenshot: Gemini, the Tesseract fallback and the review table (R40–R45), with the same type and size limits (PNG, JPEG or WebP, ≤ 10 MB). A pasted image SHALL never be stored (R42).<br>• The area SHALL show the tip "Press Windows+Shift+S, select the Assignments list, then click here and press Ctrl+V."<br>• WHERE the browser offers the asynchronous Clipboard API, THE SYSTEM SHALL also show a "Paste from clipboard" button; elsewhere it SHALL say to use Ctrl+V instead.<br>• The file upload option SHALL remain.<br>• IF the clipboard has no image, or the image has the wrong type or is too large, THEN THE SYSTEM SHALL say so in plain words and change nothing. |

### 5.8 Export

| ID | Priority | Requirement |
|---|---|---|
| R49 | Must | WHEN the user clicks "Export to Google Calendar", THE SYSTEM SHALL download `autoplanner-YYYY-MM-DD.ics`, with import instructions for Google Calendar (3 steps) next to the button. The file SHALL contain:<br>• one `VEVENT` per future planned task block, with summary `<task title> (<course>)`, a description that includes the deadline, and `DTSTART`/`DTEND` with the `Asia/Kolkata` TZID;<br>• a UID per block that stays the same across exports;<br>• a `PRODID`. |
| R50 | Should | WHEN the "include fixed events" option is ticked, THE SYSTEM SHALL also export the fixed events inside the horizon, expanded from their recurrence. |

### 5.9 Demo mode

| ID | Priority | Requirement |
|---|---|---|
| R51 | Must | WHEN a visitor opens `?demo=1` or clicks "Try the demo", THE SYSTEM SHALL load sample data dated relative to today:<br>• an IISc-style timetable (≥ 8 classes and labs per week);<br>• ≥ 8 open tasks of mixed types, including ≥ 3 demanding tasks and ≥ 1 task longer than the max block length;<br>• default preferences with ≥ 1 blocked time;<br>• ≥ 3 learning-eligible completed tasks, so that the learning factors are not 1.0.<br>• ≥ 5 past task blocks from the previous 2 days with no feedback yet, so a visitor can mark them done (with the time taken) or not done at once.<br>It SHALL then show the planned calendar. |
| R52 | Must | WHILE in demo mode, THE SYSTEM SHALL keep all data in the session only, make no database writes, show the banner "Demo — changes are not saved", and offer "Reset demo". Demo mode SHALL work with no secrets configured. |
| R53 | Should | WHILE in demo mode, THE SYSTEM SHALL offer an "Overload the week" toggle. It adds tasks that make the plan infeasible, to show R29–R32. |

### 5.10 Benchmark

| ID | Priority | Requirement |
|---|---|---|
| R54 | Must | THE SYSTEM SHALL include a seeded workload generator. Its parameters are size (10 tasks/7 days, 20/7, 30/14) and load ratio ρ ∈ {0.6, 0.9, 1.15}. Its output:<br>• a weekday class and lab timetable, 0–3 blocked times, and default preferences;<br>• task estimates scaled to hit the target ρ (±0.05), with total work ≤ 90 % of the available slots in the horizon, so that all work fits somewhere.<br>"Now" is fixed at Monday 08:00 of a fixed week. |
| R55 | Must | THE SYSTEM SHALL include a **greedy EDF baseline**, defined as follows:<br>1. Visit the available slots in time order, skipping slots where the day's cap is reached.<br>2. In each slot, assign the open task with the earliest deadline (ties: continue the current task, then larger remaining work, then ID). Skip tasks whose current run has reached the max block length.<br>3. Work may continue past a deadline, which counts as lateness.<br>4. The baseline ignores focus windows and the min block length. |
| R56 | Must | THE SYSTEM SHALL compute these metrics with one shared module for both methods:<br>• **deadlines met**: tasks whose work is all scheduled at or before the deadline;<br>• **total lateness**: Σ max(0, finish − deadline), in hours;<br>• **preference violations**: demanding slots outside focus windows, plus blocks shorter than the min block length (not counting a task's only block when its total work is below the min);<br>• **solve time**: wall clock in seconds, including model building.<br>In the benchmark, the optimizer runs in strict mode. When strict mode is proven infeasible, the optimizer switches to a minimum-total-lateness mode. In that mode the min block length is a soft goal (D-23). |
| R57 | Must | WHEN `python -m bench.run_benchmark --seeds 10` runs, THE SYSTEM SHALL write `bench/results/results.csv` (one row per instance × method), `bench/results/REPORT.md` and `bench/results/comparison.png`. The report SHALL contain:<br>• aggregate tables by size and ρ;<br>• solve-time median, p95 and max, and the % proven optimal;<br>• environment details: CPU, Python, OR-Tools version, time limit, workers. |
| R58 | Should | THE SYSTEM SHALL show the latest `REPORT.md` and chart on a "Results" page in the app. |

### 5.11 Non-functional

| ID | Priority | Requirement |
|---|---|---|
| R59 | Must | THE SYSTEM SHALL show all times in IST and store all timestamps as UTC `timestamptz`. |
| R60 | Must | THE SYSTEM SHALL include a `pytest` suite that runs with no network, no secrets and no `private/` folder:<br>• Gemini is mocked.<br>• Storage uses an in-memory repository with the same interface as the Supabase one.<br>• Image-based tests use only the committed synthetic screenshots (R66).<br>• Tesseract tests are skipped if the binary is missing. CI installs it, so they run there. |
| R61 | Must | THE SYSTEM SHALL be deployable on Streamlit Community Cloud from the repo root. The entry point is `streamlit_app.py`, Python 3.13 is selected in the deploy settings, and the dependencies come from `requirements.txt` and `packages.txt`. |
| R62 | Must | THE SYSTEM SHALL solve only when its inputs change. Normal reruns (navigating the calendar or opening a block) SHALL reuse the stored plan. |

### 5.12 Operations

| ID | Priority | Requirement |
|---|---|---|
| R63 | Must | THE SYSTEM SHALL include a GitHub Actions workflow, `.github/workflows/supabase-keepalive.yml`, that keeps the Supabase project from pausing:<br>• It runs on schedule `0 3 */3 * *` (03:00 UTC every third day of the month, never more than 3 days apart) and on manual dispatch.<br>• Each run sends one read request to the Supabase REST API (`GET {SUPABASE_URL}/rest/v1/planners?select=id&limit=1`), using `SUPABASE_URL` and `SUPABASE_KEY` from GitHub Actions encrypted secrets.<br>• The run fails if the response is not HTTP 200.<br>• It SHALL NOT print the response body or any secret.<br>The README SHALL explain how to re-enable the workflow, because GitHub disables scheduled workflows in a public repo after 60 days with no repository activity. |
| R65 | Must | THE SYSTEM SHALL keep real Teams screenshots and their ground-truth labels only in the git-ignored folder `private/teams/` (`*.png` and `labels.json`):<br>• `.gitignore` SHALL list `private/`.<br>• No test collected by `pytest` SHALL read from `private/`.<br>• `bench/eval_import.py` reads `private/teams/` by default and accepts `--dir` to point at another folder. When the folder is missing, it SHALL exit 0 with "skipped: private fixtures not present". |
| R66 | Must | THE SYSTEM SHALL include a deterministic generator, `tests/fixtures/make_synthetic_screenshots.py`. It SHALL render ≥ 3 PNGs that imitate the Teams Assignments list layout (title, course, due line) from fictional sample data, plus a `labels.json` with the expected rows:<br>• The due lines SHALL cover relative words, weekday names (including the ambiguous same-day case), month-day without a year, and explicit dates, against a fixed import date.<br>• Each PNG SHALL carry the PNG text chunk `autoplanner-synthetic=1`.<br>• Only the generator's output is committed under `tests/fixtures/teams_synthetic/`. |
| R67 | Must | THE SYSTEM SHALL include a GitHub Actions CI workflow, `.github/workflows/ci.yml`. It runs on every push and pull request on a pinned `ubuntu-24.04` runner, sets up Python 3.13, installs `tesseract-ocr`, installs `requirements.txt` and `requirements-dev.txt`, and runs plain `pytest` from the repository root. The project is importable without being installed: pytest's `pythonpath` setting in `pyproject.toml` puts the repository root on the import path. It needs no secrets. |

## 6. Acceptance criteria

Each criterion either passes or fails. "Demo data" means the R51 data set. "Validator" means the R20 validator. Must criteria are run first. Should criteria are attempted only after every Must criterion passes.

| ID | Priority | Criterion (pass = all of the stated conditions hold) | Checks |
|---|---|---|---|
| AC-1 | Must | Click "Create my planner", add 1 event and 1 task, then open the link in a new private window: the same event, task and plan load. The planner ID is 43 characters long and matches `^[A-Za-z0-9_-]{43}$`. 1,000 generated IDs are all distinct. | R1–R3 |
| AC-2 | Must | Open `?p=doesnotexist` and `?p=<valid ID with one character changed>`: both show the identical "Planner not found" message, and the `planners` row count does not change. | R4 |
| AC-3 | Must | `.gitignore` contains `.streamlit/secrets.toml`. `git log -p --all` contains no match for any **real key format**:<br>• `sb_secret_[A-Za-z0-9_-]{20,}` (Supabase secret key);<br>• `AQ\.[A-Za-z0-9_-]{20,}` (Google auth key);<br>• `AIza[0-9A-Za-z_-]{20,}` (Google API key);<br>• `eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}` (a JWT, such as the legacy `service_role` key).<br>Mentions of key names in prose and short placeholders such as `sb_secret_REPLACE_ME` don't match. | R5, C5 |
| AC-4 | Must | On the live app, `?demo=1` shows ≥ 8 fixed events and ≥ 8 task blocks within 10 s. Run locally with an empty secrets file, the demo also loads with no exception. With Supabase configured, the row counts in all tables are unchanged after 5 minutes of demo use. | R7, R51, R52 |
| AC-5 | Must | Every plan from the demo and the benchmark run passes the rule set for its type (R20), with 0 failures:<br>• optimizer plans satisfy all of R14.1–R14.6;<br>• greedy and best-effort plans satisfy the base rules plus R14.4 and R14.6.<br>The deadline misses and short blocks of greedy and best-effort plans appear as counts in `results.csv`. | R14, R20, R55 |
| AC-6 | Must | On demo data, every task with a deadline inside the horizon has all of its remaining work scheduled at or before its deadline. | R14 |
| AC-7 | Must | Unit test: one 5 h task, max block 2 h, min block 1 h, ample free time. The plan has ≥ 3 blocks, each 1–2 h long, totalling exactly 5 h. | R15 |
| AC-8 | Must | Unit test: two demanding tasks whose total work fits inside the focus windows before their deadlines. 100 % of their slots are inside focus windows. | R16 |
| AC-9 | Must | On the live app with demo data, mark a started block not done, 5 times in a row. Each time:<br>• remaining work rises by the block length;<br>• all done and past blocks are unchanged;<br>• no block starts before the current slot;<br>• the validator passes;<br>• the calendar updates in ≤ 5 s. | R23, R62 |
| AC-10 | Must | Unit test: a fixture that is infeasible by exactly 3.0 h. The diagnosis reports H = 3.0 h. Each "Extend deadline" option, applied alone, gives a strict-feasible plan. The "Cut hours" option, applied, gives a strict-feasible plan. No exception is raised. | R29, R30, R32 |
| AC-11 | Must | Unit test: with the solver stubbed to return `UNKNOWN`, the planner returns the greedy plan with `fallback=True`. The plan passes the greedy rule set (R20) with 0 failures, and it carries deadline-miss and short-block counts, even when they are 0. | R19, R20 |
| AC-12 | Must | Unit test: a task whose deadline is 1 h before "now", with work remaining, is marked `overdue` and is not in the plan. | R33 |
| AC-13 | Must | Unit tests:<br>• 3 learning-eligible completed `lab_report` tasks with raw 2 h / actual 3 h each give r = 1.5 and factor = 1.3. A new lab report with raw 2 h is prefilled as 2.5 h (2.6 rounded to the nearest 0.5).<br>• Adding a 4th completed lab report (raw 2 h, actual 6 h) that has one unconfirmed block leaves the factor at 1.3.<br>• Confirming that block in the R26 prompt makes the task eligible, and the factor changes.<br>• With no history the factor is 1.0.<br>• A factor that would exceed 2.5 is clamped to 2.5. | R25, R26, R36–R38 |
| AC-14 | Must | The date-resolver table test passes all of its cases (≥ 25), including the ones below, with import date **Wed 2026-10-14**. Each case checks the date and the flag.<br>• "Due tomorrow at 11:59 PM" → 2026-10-15 23:59, *inferred*<br>• "Due today at 5:00 PM" → 2026-10-14 17:00, *inferred*<br>• "Due Friday" → 2026-10-16 23:59, *inferred*<br>• "Due Wednesday 9 AM" → 2026-10-21 09:00, *ambiguous*<br>• "Due Oct 20" → 2026-10-20 23:59, *inferred* (year and time assumed)<br>• "Due 3 Jan" → 2027-01-03 23:59, *inferred*<br>• "Due yesterday at 11:59 PM" → 2026-10-13 23:59, *inferred*<br>• "Due October 17, 2026 21:00" → 2026-10-17 21:00, no flag<br>• "Due sometime" → empty, *unresolved* | R43 |
| AC-15 | Must | Unit test with a mocked Gemini response of 5 rows: one `completed`, one a duplicate of an existing task, one "Due Wednesday" (ambiguous), and one "Due sometime" (unresolved).<br>• The review table has 5 rows, with the ambiguous and unresolved rows first.<br>• Their Date check cells show "⚠" and "✖ needs a date".<br>• "Add selected" is refused until the unresolved row is given a date or unticked.<br>• The repository holds 0 new tasks before "Add selected" succeeds. | R40, R43–R45 |
| AC-16 | Must | Unit tests: with the Gemini key missing, and with the Gemini client mocked to time out, the pipeline uses Tesseract, and the engine label is "Tesseract (fallback)". | R41, R42 |
| AC-17 | Must (local only) | Run by the owner on their own machine; never in CI. `python -m bench.eval_import` runs on the 3 real screenshots in `private/teams/`, with every visible assignment labelled in `private/teams/labels.json`. A row is correct when the normalised title and the resolved deadline both match the label. Gemini gets ≥ 90 % of rows correct and Tesseract ≥ 60 %. The report gives the row count next to each percentage. The aggregate percentages may be copied into the README. No titles, courses or images are copied. | R40–R43, R65 |
| AC-18 | Must | The paste parser turns `tests/fixtures/paste_samples.txt` into exactly the expected list of (title, course, deadline, flag) records. | R43, R46 |
| AC-19 | Must | The exported `.ics` file parses with `icalendar`. There is one `VEVENT` per future planned block, and each has a UID, a `DTSTART` and a `DTEND`. A block from 21:00 to 22:00 IST appears as 15:30–16:30 UTC when converted. Two exports of the same plan have identical UIDs. **Manual:** importing the file into a Google Calendar test calendar shows the blocks at the correct local times. | R49, R59 |
| AC-20 | Must | `python -m bench.run_benchmark --seeds 10` finishes and writes 90 instances × 2 methods = 180 CSV rows, plus `REPORT.md` and `comparison.png`. | R54–R57 |
| AC-21 | Must | On every benchmark instance where strict CP-SAT finds a plan, the optimizer meets 100 % of deadlines. | R14, R56 |
| AC-22 | Must | Summed over all 90 instances: optimizer deadlines met ≥ greedy, optimizer total lateness ≤ greedy, and optimizer preference violations < greedy. | R16, R55, R56 |
| AC-23 | Must | `REPORT.md` reports solve-time median, p95 and max for each size. For the 20-task / 7-day size on the dev machine (time limit 10 s, 4 workers): median ≤ 2 s and p95 ≤ 5 s. | R18, R57 |
| AC-24 | Must | `pytest` passes with networking disabled, no `secrets.toml` present, and no `private/` folder present. | R60, R65 |
| AC-25 | Must | The app is live on a `*.streamlit.app` URL. There, the demo loads (AC-4), and with Gemini disabled through secrets, an import of a synthetic screenshot falls back to Tesseract and produces review rows. | R41, R61, R66 |
| AC-26 | Must | Unit test: an event entered as 09:10–10:20 is stored as 09:00–10:30, and the user sees a notice. | R9 |
| AC-27 | Must | Unit tests with a 7-day horizon:<br>• A task due 14 days from now with 10 h remaining gets exactly 5 h inside the horizon, and is labelled "continues beyond this plan".<br>• If the task is demanding and focus windows are free, its share is placed in them.<br>• When the share cannot fit, the infeasibility report offers a cut option for it and no extend option. | R16, R17, R29 |
| AC-28 | Must | `.github/workflows/supabase-keepalive.yml` has the schedule `0 3 */3 * *` and a `workflow_dispatch` trigger. A manual run on GitHub succeeds with HTTP 200. Its log contains no secret value and no response body. | R63 |
| AC-29 | Must | Unit test, after a mocked screenshot import:<br>• the Gemini mock received the image as inline bytes, and no Files API upload was called;<br>• the repository holds no image or bytes data;<br>• no file was created under the working directory or the temp directory;<br>• the pipeline's returned state contains only text rows. | R40, R42, C9 |
| AC-36 | Must | Running the generator twice gives identical `labels.json` files and ≥ 3 PNGs, each with the `autoplanner-synthetic=1` chunk. `tests/test_synthetic_fixtures.py` runs the Tesseract path of the import pipeline on the committed synthetic screenshots, and ≥ 80 % of rows match `labels.json` (normalised title and resolved deadline). The test is skipped only when the Tesseract binary is missing. | R41, R43, R46, R66 |
| AC-37 | Must | No real screenshots are committed:<br>• `.gitignore` lists `private/`, and `git ls-files private/` prints nothing.<br>• `tests/test_synthetic_fixtures.py` fails if any PNG tracked under `tests/fixtures/` lacks the `autoplanner-synthetic=1` chunk.<br>• `python -m bench.eval_import` with no `private/` folder exits 0 and prints "skipped: private fixtures not present". | C10, R65, R66 |
| AC-38 | Must | The CI workflow runs on a push to `main` and finishes green, and the Tesseract-based tests in its log ran rather than being skipped. | R60, R67 |
| AC-40 | Must | Two checks:<br>• Using the **anon** key, a select on each of the five tables returns 0 rows, and an insert is rejected.<br>• Repository contract test: with planners A and B both holding data, no read made for A returns any of B's rows. | R6 |
| AC-41 | Must | Each of these is rejected, with the reason shown at its field and 0 tasks saved: an empty title, an estimate of 0 h, an estimate of 40.5 h, and a past deadline. A valid task is saved as `open`, with `demanding` taken from the type table (`project` → true, `reading` → false). | R10, R11 |
| AC-42 | Must | Each of these changes produces a new plan with no further user action: editing a task's estimate, deleting a task, adding an event, and changing a preference. | R12 |
| AC-43 | Must | These preference cases behave as follows:<br>• day start 23:00 with "no work at/after" 23:00 is rejected;<br>• min block 3 h with max block 2 h is rejected;<br>• with day start 08:00, a focus window of 06:00–09:00 is saved as 08:00–09:00, and the user sees a notice. | R13 |
| AC-44 | Must | On demo data:<br>• the calendar offers week and day views;<br>• the initial week view starts 2 days before today, and its visible range includes ≥ 5 unconfirmed past blocks;<br>• navigating forward reaches the last horizon day;<br>• fixed events, blocked times and task blocks each appear at least once;<br>• a first click on a block selects it, shows a notice and requests a scroll to the highlighted details panel, and a repeated rerun with the same click does not.<br>**Manual:** on the live app, clicking a block scrolls to its highlighted details. | R21, R51 |
| AC-45 | Must | Marking a block done with 75 actual minutes stores `done`, confirmed, and 75 minutes. Marking one done with no value stores its planned length. A past block marked done no longer shows the "unconfirmed" badge. | R24 |
| AC-46 | Must | Unit test with a fake clock where each solve takes 4 s: diagnosis starts no solve after 15 s have passed. It returns the options found so far and the best-effort plan, with `cut_short = true`. | R34 |
| AC-47 | Must | App test (Streamlit `AppTest`): the solver, the storage and the Gemini client are each stubbed in turn to raise an exception. Each time, the page shows a plain-language message, the rendered page contains no "Traceback", and the previous tasks and plan are unchanged. | R35 |
| AC-48 | Must | Unit tests:<br>• a PNG sent by the paste area as a data URL decodes to exactly the original bytes;<br>• non-image types, invalid base64, malformed payloads and images over 10 MB are rejected with a plain message;<br>• the decoded image goes through the same pipeline as an upload: Gemini rows labelled "Gemini", or "Tesseract (fallback)" rows when Gemini can't be used;<br>• after a pasted import, no image bytes remain in the repository or in the returned state.<br>**Manual**, on the live app in Chrome, Edge, Firefox and Brave: Windows+Shift+S, then clicking the area and pressing Ctrl+V produces review rows. The "Paste from clipboard" button works where it is shown. | R42, R68 |
| AC-39 | Should | Marking a 60-minute block not done with 30 minutes completed counts 30 minutes as done and returns exactly 30 minutes to the task's remaining work. | R28 |
| AC-30 | Should | After "Delete my planner" is confirmed, the planner has 0 rows in every table, and its old link shows "Planner not found". | R8 |
| AC-31 | Should | Marking a future block "can't do this slot" creates a one-off blocked time over that block, and the new plan has no task work in it. | R27 |
| AC-32 | Should | Unit test: the 21st Gemini call for a planner in one IST day uses Tesseract and shows the limit message. | R47 |
| AC-33 | Should | In the demo, turning on "Overload the week" shows the infeasibility banner with ≥ 1 verified option. Applying that option clears the banner. | R53, R29–R32 |
| AC-34 | Should | Unit test: re-solving an unchanged instance with the stability goal on reproduces the previous future blocks exactly. | R64 |
| AC-35 | Should | The demo shows:<br>• the plan summary table;<br>• the Estimate insights panel;<br>• a working "Try with a sample screenshot" button;<br>• the Results page with the latest report.<br>With "include fixed events" ticked, the `.ics` file contains the fixed events inside the horizon. | R22, R39, R48, R50, R58 |

## 7. Non-goals

- User accounts, login, OAuth, or sharing a planner with a group.
- Any Microsoft Teams / Graph API integration (C8). Screenshot and paste only.
- Two-way Google Calendar sync or Google OAuth. Export is a one-way `.ics` download.
- Notifications, reminders, email, or a mobile app.
- Recurring tasks, task dependencies, and earliest-start ("release") dates on tasks.
- Time zones other than IST, slots finer than 30 minutes, and horizons longer than 14 days.
- Different focus windows per weekday (the same windows apply every day).
- Machine learning beyond the per-type ratio correction in R37.
- Re-estimating tasks that are already open when a learning factor changes.
- Handling simultaneous edits from two tabs on the same planner (last write wins).
- Importing from LMSs other than Teams (Moodle, Canvas and so on).
- Paid tiers of any service.

## 8. Decisions

These questions were open in earlier drafts or in PLAN.md §5. The owner resolved D-1 to D-10 on 2026-10-14, and D-11 to D-20 on 2026-10-15. D-21 to D-23 are small clarifications made during the build under the owner's standing rule (plan defaults chosen, no AC target or scope changed).

| ID | Question | Decision | Reflected in |
|---|---|---|---|
| D-1 (OQ-1) | Should a past block with no feedback count as done or not done? | It counts as **done** for scheduling and shows an "unconfirmed" badge. Unconfirmed blocks are **excluded from learning**. Only user-confirmed blocks update the factor. | R25, R26, R36, R37, AC-13 |
| D-2 (OQ-2) | Is "Due Wednesday" on a Wednesday today or next week? | **Next week.** Inferred and ambiguous dates are highlighted in the review table so the user can correct them. | R43, R44, AC-14, AC-15 |
| D-3 (OQ-3) | Where do the import test fixtures come from? | Moved to **day 1**. The owner provides 3 real Teams Assignments screenshots (cropped, name removed) before the screenshot-import phase. The ground-truth `labels.json` is created together with the owner at that point. Both are stored in the git-ignored `private/teams/` folder (see D-11). | AC-17, R65, §10, build order |
| D-4 (OQ-4) | Is it acceptable that Gemini's free tier may use the inputs it receives? | **Accepted**, with a notice before upload. Screenshots are never stored after import: images are kept in memory only, sent inline (no Files API), and dropped once the review table is built. | C9, R40, R42, AC-29 |
| D-5 (OQ-5) | A Supabase free project pauses after about 7 days of inactivity. What do we do? | **In scope:** a scheduled GitHub Action pings Supabase every 3 days. | C1, C5, R63, AC-28 |
| D-6 (OQ-6) | Does `streamlit-calendar` work with Python 3.13 and click callbacks? | Default accepted: check it in the first hour of day 1. If it doesn't work, fall back to a read-only calendar plus a day list with done / not done buttons for each block. | Build order |
| D-7 (OQ-7) | Is "max work per day" hard or soft? | Default accepted: **hard**. | R14.6 |
| D-8 (OQ-8) | Are the default preferences right? | Default accepted: day 08:00–23:00, focus 09:00–12:00 and 18:00–21:00, blocks 1–2 h, 8 h a day. | §4.1 |
| D-9 (OQ-9) | Should a new learning factor re-estimate tasks that are already open? | Default accepted: **no**, it applies to new tasks only. | R38, §7 |
| D-10 (OQ-10) | Is "anyone with the link has full access" acceptable? | **Accepted.** Planner IDs must be long, random and unguessable: 256-bit CSPRNG IDs, strictly validated, never logged, and an identical "not found" response for malformed and unknown IDs. | C4, R2, R4, R5, AC-1, AC-2 |
| D-11 (OQ-11) | Will the GitHub repo be public? | **Yes, it is public.**<br>• The README explains how to re-enable the keep-alive workflow after GitHub's 60-day inactivity disable.<br>• **Real Teams screenshots are never committed.** They and their labels stay in the git-ignored `private/teams/` folder, and the AC-17 accuracy test runs locally only.<br>• Only synthetic screenshots, generated from sample data, are committed. They are used by the tests that run in CI and by the demo.<br>• Because tests now run in CI, a CI workflow is added. | C10, R48, R60, R63, R65–R67, AC-17, AC-24, AC-25, AC-36–AC-38 |
| D-12 (plan Q-1) | The greedy baseline ignores the min block length, and best-effort plans miss deadlines by design. How does the validator treat them? | There is a **base rule set** that every plan must satisfy: no overlaps, no blocked or out-of-hours time, and no clash with fixed events. On top of it, each plan type has its own rules:<br>• optimizer plans must satisfy all the hard rules;<br>• greedy-baseline and best-effort plans also keep the max block length and the daily cap, and their deadline misses and short blocks are counted and reported, not treated as failures. | R19, R20, AC-5, AC-11 |
| D-13 (plan Q-2, Q-3) | Ten requirements had no AC. | Each Must requirement among them gets a short pass/fail AC: R6 → AC-40, R10 and R11 → AC-41, R12 → AC-42, R13 → AC-43, R21 → AC-44, R24 → AC-45, R34 → AC-46, R35 → AC-47. R28 is already Should and gets AC-39. No requirement was moved to Should: each one guards security (R6), input integrity (R10, R11, R13), the core loop (R12, R21, R24), or the public app's UX (R34 caps diagnosis, which could otherwise take about 80 s on Cloud; R35 hides stack traces). | AC-39–AC-47 |
| D-14 (plan Q-4) | `PLAN.md` was not an output file. | Approved, and added to §10. | §10 |
| D-15 (plan Q-5) | Does the daily cap count work already done today? | **Yes.** Done and past blocks count toward that day's cap. | R14.6 |
| D-16 (plan Q-6) | How is a task due after the horizon scheduled? | It is given its **pro-rata share** of remaining work inside the horizon: remaining × horizon length ÷ time until the deadline, rounded up to whole slots. The share counts as work due at the horizon end, and is ranked like any other work for focus hours. | R14.3, R17, AC-27 |
| D-17 (plan Q-7) | Where are the AC-4 and AC-9 timings measured? | On the **live app**. | AC-4, AC-9 |
| D-18 (plan Q-10) | Which separators does single-line paste accept? | `—`, `–`, ` - `, `\|` and tab. | R46 |
| D-19 (plan Q-11) | Is the AC-17 accuracy bar too coarse with 3 screenshots? | Keep the thresholds, and report the row count next to each percentage. | AC-17 |
| D-20 (plan Q-8, Q-9, Q-12) | What happens to the Phase 1 smoke page, which table its write check uses, and which Gemini model is the default? | Plan-level only, with no spec change:<br>• the smoke page is removed in Phase 3;<br>• the write check uses a throwaway `planners` row that is deleted at once;<br>• the Gemini model ID is chosen and recorded in the PLAN.md Phase 1 log. | PLAN.md |
| D-21 (build) | The R16 goals with fixed caps of 3 s and 1 s left the 20-task benchmark median above AC-23's 2 s, and partial hints made CP-SAT start far from good plans. | Every goal gets a cap once a plan exists (focus 0.8 s, fewer blocks 0.5 s, earlier completion 0.3 s, lateness 1.5 s); minimum shortfall stays uncapped. CP-SAT gets a complete starting plan that respects the block-length rules (not the R55 baseline, which ignores the min block). `repair_hint` is not used: it crashed OR-Tools 9.15 with several workers. No AC target changed. | R16, R18, AC-22, AC-23 |
| D-22 (build) | R54 said all work must fit in the horizon, but ρ counted available slots without the daily cap, so "fits" was not guaranteed. | Capacity in ρ, and in the 90 % rule, counts available slots with each day capped at the max work per day. | §4.3, R54 |
| D-23 (build) | In the benchmark's minimum-lateness mode the optimizer kept the min block length as a hard rule while the R55 baseline ignores it, so the optimizer had less room and AC-22's lateness check failed (1281 h vs 1165 h). | Lateness-mode plans are best-effort plans, so, as D-12 already says, short blocks are counted, not forbidden: the min block becomes a soft goal ranked after lateness and focus. The solver starts from the less late of the two starting plans. Strict mode and diagnosis keep R14.5 hard. Result: 782 h vs 1165 h. No AC target changed. | R14.5, R20, R56, AC-22 |

## 9. Open questions

None open.

## 10. Output files

Building any file not listed here needs a changelog entry first.

| Path | Purpose |
|---|---|
| `SPEC.md` | This specification |
| `PLAN.md` | Phased implementation plan, with R# / AC-# traceability, risks, and the Phase 1 deployment log |
| `docs/interview-prep.html` | Self-contained study page for a viva on the project: summary, architecture, worked examples and a question bank (no external requests, no secrets) |
| `README.md` | What the app is, live and demo links, local setup, secrets, deployment, how to re-enable the keep-alive workflow, the `private/` fixtures convention, benchmark and import-accuracy headline numbers |
| `requirements.txt` | Pinned runtime dependencies |
| `requirements-dev.txt` | Test and dev dependencies (`pytest`, etc.) |
| `packages.txt` | apt packages for Streamlit Cloud: `tesseract-ocr`, `tesseract-ocr-eng` |
| `pyproject.toml` | Project metadata and pytest configuration |
| `.gitignore` | Includes `.streamlit/secrets.toml`, `private/`, `__pycache__/`, `.venv/` |
| `.streamlit/config.toml` | Theme and server settings |
| `.streamlit/secrets.toml.example` | Placeholder keys: `SUPABASE_URL`, `SUPABASE_KEY`, `GEMINI_API_KEY`, `GEMINI_MODEL` |
| `.github/workflows/supabase-keepalive.yml` | Supabase keep-alive ping every 3 days (R63) |
| `.github/workflows/ci.yml` | Runs `pytest` with Tesseract on every push and pull request (R67) |
| `streamlit_app.py` | Entry point. Routes `?p=` and `?demo=1`, and builds the page layout |
| `autoplanner/__init__.py` | Package marker |
| `autoplanner/config.py` | Constants (TZ, slot size, type table, defaults) and secret access |
| `autoplanner/models.py` | Dataclasses: Event, Task, Preferences, Block, Plan, Diagnosis |
| `autoplanner/timegrid.py` | Slot grid, IST handling, availability mask, snapping |
| `autoplanner/solver.py` | CP-SAT model: strict, minimum-shortfall and minimum-lateness modes |
| `autoplanner/diagnose.py` | Infeasibility diagnosis and verified extend / cut options |
| `autoplanner/baseline.py` | Greedy EDF baseline |
| `autoplanner/validate.py` | Independent hard-constraint validator |
| `autoplanner/metrics.py` | Shared benchmark and plan metrics |
| `autoplanner/planner.py` | Orchestration: remaining work, replan, fallback, overdue |
| `autoplanner/learning.py` | Correction factors (confirmed blocks only) and the corrected-estimate suggestion |
| `autoplanner/ics_export.py` | `.ics` generation |
| `autoplanner/storage.py` | Repository interface, `SupabaseRepo`, `MemoryRepo`, planner ID generation and validation |
| `autoplanner/demo.py` | Demo data relative to today, overload scenario |
| `autoplanner/importers/__init__.py` | Package marker |
| `autoplanner/importers/dates.py` | Due-text → IST datetime resolver with inferred / ambiguous / unresolved flags |
| `autoplanner/importers/text_parser.py` | Rule-based paste and OCR-text parser |
| `autoplanner/importers/gemini_vision.py` | Gemini structured extraction (inline image bytes) |
| `autoplanner/importers/ocr.py` | Tesseract fallback |
| `autoplanner/importers/pipeline.py` | Engine selection, type inference, default estimates, dedupe, date flags, rate limit, image disposal |
| `autoplanner/ui/__init__.py` | Package marker |
| `autoplanner/ui/calendar_view.py` | Calendar and block actions |
| `autoplanner/ui/tasks_view.py` | Manual entry, the task / event tables, the mark-complete prompt |
| `autoplanner/ui/import_view.py` | Screenshot and paste import, review table with the Date check column |
| `autoplanner/ui/clipboard_paste.py` | Paste-a-screenshot component: browser paste event plus an optional Clipboard API button; decodes and checks the pasted image (R68) |
| `autoplanner/ui/settings_view.py` | Preferences, delete planner |
| `autoplanner/ui/results_view.py` | Benchmark results page (Should) |
| `db/schema.sql` | Tables `planners`, `events`, `tasks`, `blocks`, `import_log`; RLS enabled, no anon policies |
| `bench/__init__.py` | Package marker |
| `bench/generate.py` | Seeded workload generator |
| `bench/run_benchmark.py` | Benchmark runner |
| `bench/eval_import.py` | Import accuracy evaluation. Defaults to `private/teams/` and is local only (AC-17). Accepts `--dir` |
| `bench/results/results.csv` | Generated benchmark rows |
| `bench/results/REPORT.md` | Generated benchmark report |
| `bench/results/comparison.png` | Generated comparison chart |
| `tests/conftest.py` | Fixtures: fixed "now", MemoryRepo, Gemini mock |
| `tests/test_timegrid.py` | Grid and snapping tests (AC-26) |
| `tests/test_solver.py` | Solver tests (AC-6–AC-8, AC-27) |
| `tests/test_diagnose.py` | Infeasibility diagnosis tests (AC-10) |
| `tests/test_baseline.py` | Greedy EDF tests |
| `tests/test_validate.py` | Validator tests: the base rules, each plan type's rules, and the reported counts (AC-5) |
| `tests/test_inputs.py` | Task and preference validation, and auto-replan on edit (AC-41–AC-43) |
| `tests/test_app.py` | Streamlit `AppTest` tests: the calendar views, block actions and error handling (AC-44, AC-45, AC-47) |
| `tests/test_planner_replan.py` | Replan, fallback and overdue tests (AC-9 logic, AC-11, AC-12) |
| `tests/test_learning.py` | Learning tests (AC-13) |
| `tests/test_dates.py` | Date-resolver table and flag tests (AC-14) |
| `tests/test_text_parser.py` | Paste parser tests (AC-18) |
| `tests/test_import_pipeline.py` | Import pipeline, fallback and no-retention tests (AC-15, AC-16, AC-29) |
| `tests/test_ics_export.py` | Export tests (AC-19) |
| `tests/test_storage_memory.py` | Repository contract and planner ID tests (AC-1, AC-2 logic) |
| `tests/test_demo.py` | Demo data invariants (R51) |
| `tests/test_synthetic_fixtures.py` | Generator determinism, the synthetic-marker guard, and Tesseract accuracy on synthetic images (AC-36, AC-37) |
| `tests/fixtures/paste_samples.txt` | Paste parser input and expected output |
| `tests/fixtures/make_synthetic_screenshots.py` | Generator for the synthetic Teams-style screenshots (R66) |
| `tests/fixtures/teams_synthetic/*.png` | Generated synthetic screenshots (≥ 3). Used in CI tests, AC-25 and R48 |
| `tests/fixtures/teams_synthetic/labels.json` | Generated expected rows for those screenshots |

**Local only, never committed** (git-ignored through `private/`): `private/teams/*.png`, the 3 real screenshots, and `private/teams/labels.json`, their ground truth (D-3, D-11).

### 3-day build order

All Must criteria are completed first. Should items start only after every Must AC passes. The detailed, task-level plan is in `PLAN.md`. Its Phase 1 (a deployment check) comes before the Day 1 items below.

| Day | Must scope | Must ACs to pass by end of day |
|---|---|---|
| 1 | 1. Check `streamlit-calendar` (D-6), in the first hour.<br>2. Commit `.gitignore` with `private/` **before** any real screenshot reaches the working tree. Then collect the 3 screenshots into `private/teams/` and write `labels.json` with the owner (D-3, D-11).<br>3. Build config, models, timegrid, solver (strict mode), validator, baseline, metrics, demo data, and the calendar UI in demo mode. | AC-4 (demo part), AC-5–AC-8, AC-11, AC-26, AC-27, AC-44 |
| 2 | Storage and planner link, keep-alive and CI workflows, manual entry, settings, done / not done replan, mark-complete prompt, diagnosis, learning, `.ics` export | AC-1–AC-3, AC-9, AC-10, AC-12, AC-13, AC-19, AC-28, AC-38, AC-40–AC-43, AC-45–AC-47 |
| 3 | Date resolver with flags, paste parser, synthetic screenshot generator, Gemini and Tesseract import, review table, image disposal, benchmark and report, local accuracy run, deploy, README | AC-14–AC-18, AC-20–AC-25, AC-29, AC-36, AC-37 |
| Leftover time | Should items, in this order: R53, R22, R39, R27, R28, R64, R50, R47, R48, R8, R58 | AC-30–AC-35, AC-39 |

## 11. Changelog

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-14 | Shubham Meghani (with Claude) | Initial draft: goal, users, constraints, I/O, R1–R62, AC-1–AC-27, output files, non-goals, open questions |
| 0.2 | 2026-10-14 | Shubham Meghani (with Claude) | Resolved OQ-1–OQ-10 into §8 Decisions (D-1–D-10). Requirements and ACs moved into tables with a Priority column (Must / Should) replacing P0 / P1. Planner IDs raised to 256 bits with strict validation (R2, R4, R5). Learning uses confirmed blocks only (R25, R26, R36, R37). Date flags and Date check column (R43, R44). No screenshot retention and inline upload (C9, R40, R42). Supabase keep-alive workflow (R63). Stability split out of R16 into R64 (Should). R50 demoted to Should. Updated AC-1, AC-2, AC-13–AC-15, AC-17, AC-18; added AC-28–AC-35. Added OQ-11. Added the keep-alive workflow and `labels.json` to the output files. Build order moves fixtures to day 1 and adds a Should phase. |
| 0.3 | 2026-10-15 | Shubham Meghani (with Claude) | Resolved OQ-11 as D-11: the repo is public. Added C10. Real screenshots and their labels stay in the git-ignored `private/teams/` and are never committed (R65). AC-17 is local only. Synthetic Teams-style screenshots are generated from sample data and are the only committed images (R66). They are used by CI, AC-25 and R48. Added the CI workflow (R67). R63 now requires the README note on re-enabling the keep-alive workflow. Updated R48, R60, AC-17, AC-24, AC-25 and D-3; added AC-36–AC-38. Output files: added `ci.yml`, the generator, the synthetic fixtures and `test_synthetic_fixtures.py`; removed `tests/fixtures/teams/`. No open questions remain. |
| 0.4 | 2026-10-15 | Shubham Meghani (with Claude) | Resolved the PLAN.md §5 questions as D-12–D-20. The validator uses base rules plus per-plan-type rules; greedy and best-effort deadline misses and short blocks are reported, not failures (R19, R20, AC-5, AC-11). Tasks due after the horizon get a pro-rata share (R14.3, R17, AC-27). The daily cap counts work already done today (R14.6). Paste separators (R46). AC-4 and AC-9 are timed on the live app. AC-17 reports row counts. Added Must AC-40–AC-47 for R6, R10–R13, R21, R24, R34 and R35, and Should AC-39 for R28; every requirement now has an AC, and none moved to Should. Output files: added `PLAN.md`, `tests/test_inputs.py` and `tests/test_app.py`. |
| 0.5 | 2026-10-15 | Shubham Meghani (with Claude) | AC-3 now matches only real key formats (`sb_secret_` + 20 characters, `AQ.` + 20, `AIza` + 20, JWTs). The v0.4 patterns also matched key names mentioned in SPEC.md and PLAN.md, so AC-3 could never pass. |
| 0.6 | 2026-10-15 | Shubham Meghani (with Claude) | R16: the soft goals are solved lexicographically, one after another, instead of as one weighted sum. Fewer blocks gets ≤ 3 s, and earlier completion gets ≤ 1 s with a 10 % gap; it is now measured in day offsets rather than block end slots. Reason: on demo weeks the weighted model could not be proven optimal within the 10 s limit, which broke AC-4, AC-9 and AC-23. The plan found in 0.5 s was as good as the one after 10 s. No AC target changed. |
| 0.7 | 2026-10-15 | Shubham Meghani (with Claude) | D-21: per-goal time caps for R16 and a complete, rule-respecting starting plan for CP-SAT. D-22: ρ and the 90 % rule count capacity with the daily cap. No AC target changed. |
| 0.8 | 2026-10-15 | Shubham Meghani (with Claude) | D-23: in the benchmark's minimum-lateness mode the min block length is a soft goal (consistent with D-12); R56 updated. No AC target changed. |
| 0.9 | 2026-10-15 | Shubham Meghani (with Claude) | R67: CI is pinned to `ubuntu-24.04` and runs plain `pytest`. The package is importable through pytest's `pythonpath` setting. CI had failed with `No module named 'autoplanner'`; local runs used `python -m pytest`, which hid the problem. |
| 0.10 | 2026-10-15 | Shubham Meghani (with Claude) | R21: the week view opens 2 days before today, and clicking a block confirms the selection, scrolls to its details and highlights them. R51: the demo has ≥ 5 past blocks from the previous 2 days with no feedback. AC-44 extended. Reason: live, the past blocks were hidden behind "‹", so AC-9 couldn't be checked. |
| 0.11 | 2026-10-16 | Shubham Meghani (with Claude) | New R68 (Must): paste a screenshot from the clipboard (Ctrl+V) on the Import tab, using the browser paste event, into the same import pipeline, never stored; optional Clipboard API button. New AC-48. Output file `autoplanner/ui/clipboard_paste.py`. Reason: most users take screenshots with Windows+Shift+S and never save a file. |
| 0.12 | 2026-10-27 | Shubham Meghani (with Claude) | Output files: added `docs/interview-prep.html`, a self-contained interview-prep page. No requirement or AC changed. |
