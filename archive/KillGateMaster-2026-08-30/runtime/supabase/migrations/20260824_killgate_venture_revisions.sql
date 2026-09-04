-- Optimistic concurrency for venture JSON state.
-- A stale tab/device must never silently overwrite newer validation evidence.

alter table public.ventures
  add column if not exists revision bigint not null default 1;

alter table public.ventures
  drop constraint if exists ventures_revision_positive;

alter table public.ventures
  add constraint ventures_revision_positive check (revision >= 1);
