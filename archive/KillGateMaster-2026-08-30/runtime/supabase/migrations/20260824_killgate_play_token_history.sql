-- Preserve every verified Google Play subscription token hash so delayed RTDN
-- messages can still resolve the owning Killgate account after a resubscribe or
-- replacement changes subscription_entitlements.purchase_token_hash.

create table if not exists public.play_purchase_token_owners (
  purchase_token_hash text primary key check (char_length(purchase_token_hash) = 64),
  user_id uuid not null references auth.users(id) on delete cascade,
  product_id text not null,
  first_verified_at timestamptz not null default now(),
  last_verified_at timestamptz not null default now()
);

alter table public.play_purchase_token_owners enable row level security;
revoke all on table public.play_purchase_token_owners from anon, authenticated;
grant select, insert, update on table public.play_purchase_token_owners to service_role;

drop policy if exists play_purchase_token_owners_customer_deny on public.play_purchase_token_owners;
create policy play_purchase_token_owners_customer_deny
  on public.play_purchase_token_owners
  as restrictive
  for all
  to anon, authenticated
  using (false)
  with check (false);
