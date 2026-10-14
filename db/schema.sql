-- AutoPlanner schema (SPEC R6, R36, §4.1). Run once in the Supabase SQL editor.
-- All timestamps are timestamptz (UTC); the app shows them in Asia/Kolkata (R59).
-- RLS is enabled on every table with NO policies, so the anon/publishable key
-- can neither read nor write. The app uses the server-side secret key only.

create extension if not exists pgcrypto;

create table if not exists planners (
    id          text primary key check (id ~ '^[A-Za-z0-9_-]{43}$'),  -- R2: 256-bit token
    prefs       jsonb not null default '{}'::jsonb,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

-- Fixed events and blocked times: exactly one of on_date (one-off) or weekdays (weekly).
create table if not exists events (
    id          uuid primary key default gen_random_uuid(),
    planner_id  text not null references planners(id) on delete cascade,
    title       text not null check (length(trim(title)) > 0),
    kind        text not null check (kind in ('class', 'lab', 'other', 'blocked')),
    start_time  time not null,
    end_time    time not null,
    on_date     date,
    weekdays    smallint[] check (weekdays <@ array[0,1,2,3,4,5,6]::smallint[]),  -- 0 = Monday
    until_date  date,
    created_at  timestamptz not null default now(),
    check (end_time > start_time),
    check ((on_date is null) <> (weekdays is null))
);

create table if not exists tasks (
    id                 uuid primary key default gen_random_uuid(),
    planner_id         text not null references planners(id) on delete cascade,
    title              text not null check (length(trim(title)) > 0),
    course             text,
    type               text not null check (type in
                         ('assignment', 'lab_report', 'project', 'exam_prep', 'reading', 'quiz', 'other')),
    est_hours_raw      numeric(4,1) not null check (est_hours_raw between 0.5 and 40),
    est_hours          numeric(4,1) not null check (est_hours > 0 and est_hours <= 100),  -- after learning factor
    deadline           timestamptz not null,
    demanding          boolean not null,
    status             text not null default 'open' check (status in ('open', 'completed', 'overdue')),
    source             text not null default 'manual' check (source in ('manual', 'paste', 'screenshot', 'demo')),
    actual_hours       numeric(5,2) check (actual_hours >= 0),
    learning_eligible  boolean not null default false,
    created_at         timestamptz not null default now(),
    completed_at       timestamptz
);

-- confirmed = status in ('done', 'not_done'); a past 'planned' block is unconfirmed (R25).
create table if not exists blocks (
    id              uuid primary key default gen_random_uuid(),
    planner_id      text not null references planners(id) on delete cascade,
    task_id         uuid not null references tasks(id) on delete cascade,
    start_at        timestamptz not null,
    end_at          timestamptz not null,
    status          text not null default 'planned' check (status in ('planned', 'done', 'not_done', 'skipped')),
    actual_minutes  integer check (actual_minutes >= 0),  -- done: actual length; not_done: minutes completed (R28)
    plan_version    integer not null default 0,
    check (end_at > start_at)
);

-- Gemini calls, for the per-planner daily limit (R47).
create table if not exists import_log (
    id          bigint generated always as identity primary key,
    planner_id  text not null references planners(id) on delete cascade,
    engine      text not null check (engine in ('gemini', 'tesseract')),
    created_at  timestamptz not null default now()
);

create index if not exists events_planner_idx     on events (planner_id);
create index if not exists tasks_planner_idx      on tasks (planner_id);
create index if not exists blocks_planner_idx     on blocks (planner_id);
create index if not exists blocks_task_idx        on blocks (task_id);
create index if not exists import_log_planner_idx on import_log (planner_id, created_at);

alter table planners   enable row level security;
alter table events     enable row level security;
alter table tasks      enable row level security;
alter table blocks     enable row level security;
alter table import_log enable row level security;
