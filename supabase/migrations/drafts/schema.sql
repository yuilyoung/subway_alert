-- DRAFT ONLY: not a Supabase CLI-generated migration. Do not deploy as-is.
-- Creates owner-scoped data for a future authenticated server integration.
-- No Supabase project has been modified.

create table public.commute_favorites (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  slot smallint not null check (slot between 1 and 5),
  label text not null check (char_length(btrim(label)) between 1 and 80),
  line_id text not null check (char_length(btrim(line_id)) between 1 and 40),
  origin_station_id text not null check (char_length(btrim(origin_station_id)) between 1 and 80),
  destination_station_id text not null check (char_length(btrim(destination_station_id)) between 1 and 80),
  -- Bits 0..6 represent Monday..Sunday. Times are Asia/Seoul local time.
  weekday_mask smallint,
  starts_at time,
  ends_at time,
  auto_enabled boolean not null default false,
  created_at timestamptz not null default now(),
  constraint favorite_station_distinct check (origin_station_id <> destination_station_id),
  constraint favorite_schedule_valid check (
    (weekday_mask is null and starts_at is null and ends_at is null and not auto_enabled)
    or
    (weekday_mask is not null and weekday_mask between 1 and 127
      and starts_at is not null and ends_at is not null and starts_at < ends_at)
  ),
  -- A slot per user is concurrency-safe and cannot exceed five.
  constraint favorite_slot_per_user unique (user_id, slot)
);

create table public.tracking_sessions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  line_id text not null check (char_length(btrim(line_id)) between 1 and 40),
  origin_station_id text not null check (char_length(btrim(origin_station_id)) between 1 and 80),
  destination_station_id text not null check (char_length(btrim(destination_station_id)) between 1 and 80),
  train_id text not null check (char_length(btrim(train_id)) between 1 and 80),
  direction text not null check (char_length(btrim(direction)) between 1 and 40),
  status text not null default 'tracking' check (status in ('tracking', 'alerted', 'cancelled', 'expired')),
  created_at timestamptz not null default now(),
  ended_at timestamptz,
  constraint tracking_station_distinct check (origin_station_id <> destination_station_id),
  constraint tracking_end_state check ((status = 'tracking' and ended_at is null) or (status <> 'tracking' and ended_at is not null)),
  constraint tracking_id_owner_unique unique (id, user_id)
);

create table public.alert_logs (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null,
  user_id uuid not null references auth.users(id) on delete cascade,
  outcome text not null check (outcome in ('sent', 'failed')),
  created_at timestamptz not null default now(),
  constraint alert_session_owner_fk foreign key (session_id, user_id)
    references public.tracking_sessions(id, user_id) on delete cascade,
  -- One logical result per session; this is not a guarantee of exactly-once push delivery.
  constraint alert_one_per_session unique (session_id)
);

create index tracking_sessions_user_created_idx on public.tracking_sessions (user_id, created_at desc);
create index tracking_sessions_active_line_idx on public.tracking_sessions (line_id) where status = 'tracking';
create index alert_logs_user_created_idx on public.alert_logs (user_id, created_at desc);

alter table public.commute_favorites enable row level security;
alter table public.tracking_sessions enable row level security;
alter table public.alert_logs enable row level security;

revoke all on public.commute_favorites, public.tracking_sessions, public.alert_logs from public, anon, authenticated;
grant select, insert, update, delete on public.commute_favorites to authenticated;
grant select on public.tracking_sessions, public.alert_logs to authenticated;
grant select, insert, update, delete on public.commute_favorites, public.tracking_sessions, public.alert_logs to service_role;

create policy favorites_select_own on public.commute_favorites for select to authenticated
  using ((select auth.uid()) = user_id);
create policy favorites_insert_own on public.commute_favorites for insert to authenticated
  with check ((select auth.uid()) = user_id);
create policy favorites_update_own on public.commute_favorites for update to authenticated
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy favorites_delete_own on public.commute_favorites for delete to authenticated
  using ((select auth.uid()) = user_id);
create policy sessions_select_own on public.tracking_sessions for select to authenticated
  using ((select auth.uid()) = user_id);
create policy alerts_select_own on public.alert_logs for select to authenticated
  using ((select auth.uid()) = user_id);
