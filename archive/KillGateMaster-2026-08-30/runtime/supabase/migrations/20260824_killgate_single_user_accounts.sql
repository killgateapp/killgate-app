create table public.ventures (
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  id text not null check (char_length(id) between 3 and 64),
  state jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (user_id, id)
);
alter table public.ventures enable row level security;
grant select, insert, update, delete on table public.ventures to authenticated;
revoke all on table public.ventures from anon;
create policy "ventures_select_own" on public.ventures for select to authenticated using ((select auth.uid()) = user_id);
create policy "ventures_insert_own" on public.ventures for insert to authenticated with check ((select auth.uid()) = user_id);
create policy "ventures_update_own" on public.ventures for update to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy "ventures_delete_own" on public.ventures for delete to authenticated using ((select auth.uid()) = user_id);
create index ventures_user_updated_idx on public.ventures (user_id, updated_at desc);

create table public.subscription_entitlements (
  user_id uuid primary key references auth.users(id) on delete cascade,
  product_id text not null,
  purchase_token_hash text not null unique,
  active boolean not null default false,
  subscription_state text not null default 'unknown',
  expires_at timestamptz,
  last_verified_at timestamptz not null default now()
);
alter table public.subscription_entitlements enable row level security;
grant select on table public.subscription_entitlements to authenticated;
revoke insert, update, delete on table public.subscription_entitlements from authenticated, anon;
create policy "subscription_entitlements_select_own" on public.subscription_entitlements for select to authenticated using ((select auth.uid()) = user_id);
