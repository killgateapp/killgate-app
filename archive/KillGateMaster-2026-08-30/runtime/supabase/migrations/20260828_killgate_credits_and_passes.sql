-- Credit wallet and Venture Pass ledger. Play remains the purchase source of truth.
-- Application servers write through the service role. Users may read their own rows.

create table if not exists public.killgate_wallets (
  user_id uuid primary key references auth.users(id) on delete cascade,
  wallet_credits integer not null default 0 check (wallet_credits >= 0),
  subscription_credits integer not null default 0 check (subscription_credits >= 0),
  subscription_credits_expire_at timestamptz,
  subscription_period_id text not null default '',
  updated_at timestamptz not null default now()
);

create table if not exists public.killgate_venture_passes (
  pass_id text primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  family_id text not null default '',
  credits_remaining integer not null check (credits_remaining >= 0),
  credits_granted integer not null check (credits_granted >= 0),
  source_product text not null default '',
  expires_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists public.killgate_credit_ledger (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  kind text not null,
  amount integer,
  family_id text,
  pass_id text,
  product_id text,
  purchase_token_hash text,
  created_at timestamptz not null default now()
);

create unique index if not exists killgate_credit_ledger_purchase_hash
  on public.killgate_credit_ledger (purchase_token_hash)
  where purchase_token_hash is not null and purchase_token_hash <> '';

alter table public.killgate_wallets enable row level security;
alter table public.killgate_venture_passes enable row level security;
alter table public.killgate_credit_ledger enable row level security;

revoke all on public.killgate_wallets from public, anon;
revoke all on public.killgate_venture_passes from public, anon;
revoke all on public.killgate_credit_ledger from public, anon;
grant select on public.killgate_wallets, public.killgate_venture_passes, public.killgate_credit_ledger to authenticated;
grant all on public.killgate_wallets, public.killgate_venture_passes, public.killgate_credit_ledger to service_role;

create policy killgate_wallets_select_own on public.killgate_wallets
  for select to authenticated using (auth.uid() = user_id);
create policy killgate_passes_select_own on public.killgate_venture_passes
  for select to authenticated using (auth.uid() = user_id);
create policy killgate_ledger_select_own on public.killgate_credit_ledger
  for select to authenticated using (auth.uid() = user_id);
