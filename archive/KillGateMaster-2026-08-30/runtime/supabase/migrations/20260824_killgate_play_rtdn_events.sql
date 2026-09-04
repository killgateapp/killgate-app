-- Google Play Real-Time Developer Notification idempotency ledger.
-- Stores no raw purchase tokens and exposes no rows to end users.
create table public.play_rtdn_events (
  message_id text primary key check (char_length(message_id) between 1 and 512),
  package_name text not null check (char_length(package_name) between 1 and 300),
  event_time_millis bigint,
  notification_kind text not null check (char_length(notification_kind) between 1 and 64),
  notification_type integer,
  purchase_token_hash text check (purchase_token_hash is null or char_length(purchase_token_hash) = 64),
  processed_at timestamptz not null default now()
);

alter table public.play_rtdn_events enable row level security;
revoke all on table public.play_rtdn_events from anon, authenticated;
grant select, insert on table public.play_rtdn_events to service_role;
create policy "play_rtdn_events_no_client_access" on public.play_rtdn_events
  for all to anon, authenticated using (false) with check (false);
