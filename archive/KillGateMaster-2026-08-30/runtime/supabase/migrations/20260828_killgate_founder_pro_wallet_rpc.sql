-- Killgate paid-research wallet, Founder Pro refill, and atomic debit RPCs.
-- This migration turns the 20260828 wallet tables into the production source of
-- truth so Cloud Run instance replacement cannot lose purchased entitlements.

alter table public.killgate_credit_ledger
  add column if not exists period_id text,
  add column if not exists related_debit_id bigint;

create unique index if not exists killgate_subscription_period_grant
  on public.killgate_credit_ledger (user_id, product_id, period_id)
  where kind = 'subscription_refill' and period_id is not null and period_id <> '';

create unique index if not exists killgate_research_refund_once
  on public.killgate_credit_ledger (user_id, related_debit_id)
  where kind = 'refund_research' and related_debit_id is not null;

create or replace function public.killgate_wallet_snapshot(p_user_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_wallet public.killgate_wallets%rowtype;
  v_passes jsonb := '[]'::jsonb;
  v_hashes jsonb := '[]'::jsonb;
  v_ledger jsonb := '[]'::jsonb;
begin
  if p_user_id is null then
    raise exception 'user id is required' using errcode = '22023';
  end if;

  select * into v_wallet
    from public.killgate_wallets
   where user_id = p_user_id;

  select coalesce(jsonb_agg(to_jsonb(x) order by x.created_at), '[]'::jsonb)
    into v_passes
    from (
      select pass_id, family_id, credits_remaining, credits_granted,
             source_product, expires_at, created_at
        from public.killgate_venture_passes
       where user_id = p_user_id
    ) x;

  select coalesce(jsonb_agg(x.purchase_token_hash), '[]'::jsonb)
    into v_hashes
    from (
      select purchase_token_hash
        from public.killgate_credit_ledger
       where user_id = p_user_id
         and purchase_token_hash is not null
         and purchase_token_hash <> ''
       order by id desc
       limit 500
    ) x;

  select coalesce(jsonb_agg(to_jsonb(x) order by x.id), '[]'::jsonb)
    into v_ledger
    from (
      select id, kind, amount, family_id, pass_id, product_id,
             purchase_token_hash, period_id, related_debit_id, created_at
        from public.killgate_credit_ledger
       where user_id = p_user_id
       order by id desc
       limit 200
    ) x;

  return jsonb_build_object(
    'user_id', p_user_id::text,
    'wallet_credits', coalesce(v_wallet.wallet_credits, 0),
    'subscription_credits', case
      when v_wallet.subscription_credits_expire_at is not null
       and v_wallet.subscription_credits_expire_at <= now() then 0
      else coalesce(v_wallet.subscription_credits, 0)
    end,
    'subscription_credits_expire_at', case
      when v_wallet.subscription_credits_expire_at is not null
       and v_wallet.subscription_credits_expire_at <= now() then null
      else v_wallet.subscription_credits_expire_at
    end,
    'subscription_period_id', coalesce(v_wallet.subscription_period_id, ''),
    'passes', v_passes,
    'seen_purchase_hashes', v_hashes,
    'ledger', v_ledger
  );
end;
$$;

create or replace function public.killgate_wallet_grant(
  p_user_id uuid,
  p_product_id text,
  p_product_kind text,
  p_purchase_hash text,
  p_wallet_credits integer,
  p_venture_passes integer,
  p_credits_per_pass integer,
  p_period_days integer,
  p_subscription_period_id text,
  p_subscription_expires_at timestamptz,
  p_family_id text,
  p_requires_active_subscription boolean
)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_existing integer;
  v_index integer;
  v_pass_id text;
  v_passes jsonb := '[]'::jsonb;
  v_expiry timestamptz;
  v_pro_active boolean := false;
begin
  if p_user_id is null or p_product_id is null or btrim(p_product_id) = '' then
    raise exception 'user id and product id are required' using errcode = '22023';
  end if;
  if p_product_kind is null or btrim(p_product_kind) = '' then
    raise exception 'product kind is required' using errcode = '22023';
  end if;
  if p_wallet_credits < 0 or p_venture_passes < 0 or p_credits_per_pass < 0 then
    raise exception 'negative grant is invalid' using errcode = '22023';
  end if;
  if p_purchase_hash is not null and p_purchase_hash <> '' and p_purchase_hash !~ '^[0-9a-f]{64}$' then
    raise exception 'invalid purchase token hash' using errcode = '22023';
  end if;

  perform pg_advisory_xact_lock(hashtextextended(p_user_id::text || ':killgate-wallet', 0));

  insert into public.killgate_wallets(user_id)
  values (p_user_id)
  on conflict (user_id) do nothing;

  update public.killgate_wallets
     set subscription_credits = 0,
         subscription_credits_expire_at = null,
         updated_at = now()
   where user_id = p_user_id
     and subscription_credits_expire_at is not null
     and subscription_credits_expire_at <= now();

  if coalesce(p_requires_active_subscription, false) then
    select exists(
      select 1
        from public.subscription_entitlements
       where user_id = p_user_id
         and active = true
         and expires_at is not null
         and expires_at > now()
    ) into v_pro_active;
    if not v_pro_active then
      raise exception 'Founder Pro must be active before buying a top-up' using errcode = '23514';
    end if;
  end if;

  if p_product_kind = 'subscription' then
    if p_subscription_period_id is null or btrim(p_subscription_period_id) = '' then
      raise exception 'subscription period id is required' using errcode = '22023';
    end if;

    select count(*) into v_existing
      from public.killgate_credit_ledger
     where user_id = p_user_id
       and product_id = p_product_id
       and kind = 'subscription_refill'
       and period_id = p_subscription_period_id;
    if v_existing > 0 then
      return jsonb_build_object('ok', true, 'duplicate', true, 'subscription_period_id', p_subscription_period_id);
    end if;

    v_expiry := coalesce(
      p_subscription_expires_at,
      now() + make_interval(days => greatest(coalesce(p_period_days, 30), 1))
    );
    update public.killgate_wallets
       set subscription_credits = p_wallet_credits,
           subscription_credits_expire_at = v_expiry,
           subscription_period_id = p_subscription_period_id,
           updated_at = now()
     where user_id = p_user_id;

    insert into public.killgate_credit_ledger(
      user_id, kind, amount, product_id, period_id
    ) values (
      p_user_id, 'subscription_refill', p_wallet_credits, p_product_id, p_subscription_period_id
    );

    return jsonb_build_object('ok', true, 'duplicate', false, 'subscription_period_id', p_subscription_period_id);
  end if;

  if p_purchase_hash is not null and p_purchase_hash <> '' then
    select count(*) into v_existing
      from public.killgate_credit_ledger
     where purchase_token_hash = p_purchase_hash;
    if v_existing > 0 then
      return jsonb_build_object('ok', true, 'duplicate', true);
    end if;
  end if;

  if p_venture_passes > 0 then
    if p_credits_per_pass < 1 then
      raise exception 'venture pass grant requires credits' using errcode = '22023';
    end if;
    v_expiry := now() + make_interval(days => greatest(coalesce(p_period_days, 365), 1));
    for v_index in 1..p_venture_passes loop
      v_pass_id := 'P-' || upper(substr(replace(gen_random_uuid()::text, '-', ''), 1, 12));
      insert into public.killgate_venture_passes(
        pass_id, user_id, family_id, credits_remaining, credits_granted,
        source_product, expires_at
      ) values (
        v_pass_id, p_user_id, coalesce(btrim(p_family_id), ''),
        p_credits_per_pass, p_credits_per_pass, p_product_id, v_expiry
      );
      v_passes := v_passes || jsonb_build_array(v_pass_id);
    end loop;
  end if;

  if p_wallet_credits > 0 then
    update public.killgate_wallets
       set wallet_credits = wallet_credits + p_wallet_credits,
           updated_at = now()
     where user_id = p_user_id;
  end if;

  insert into public.killgate_credit_ledger(
    user_id, kind, amount, family_id, product_id, purchase_token_hash
  ) values (
    p_user_id,
    'grant',
    p_wallet_credits + (p_venture_passes * p_credits_per_pass),
    nullif(btrim(coalesce(p_family_id, '')), ''),
    p_product_id,
    nullif(p_purchase_hash, '')
  );

  return jsonb_build_object('ok', true, 'duplicate', false, 'passes', v_passes);
end;
$$;

create or replace function public.killgate_wallet_bind_pass(
  p_user_id uuid,
  p_pass_id text,
  p_family_id text
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_changed integer;
begin
  if p_user_id is null or btrim(coalesce(p_pass_id, '')) = '' or btrim(coalesce(p_family_id, '')) = '' then
    return false;
  end if;
  perform pg_advisory_xact_lock(hashtextextended(p_user_id::text || ':killgate-wallet', 0));
  update public.killgate_venture_passes
     set family_id = btrim(p_family_id)
   where user_id = p_user_id
     and pass_id = p_pass_id
     and family_id = ''
     and credits_remaining > 0
     and (expires_at is null or expires_at > now());
  get diagnostics v_changed = row_count;
  if v_changed = 1 then
    insert into public.killgate_credit_ledger(user_id, kind, family_id, pass_id)
    values (p_user_id, 'bind_pass', btrim(p_family_id), p_pass_id);
    return true;
  end if;
  return false;
end;
$$;

create or replace function public.killgate_wallet_debit(
  p_user_id uuid,
  p_family_id text
)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_pass_id text;
  v_subscription integer;
  v_wallet integer;
  v_debit_id bigint;
begin
  if p_user_id is null or btrim(coalesce(p_family_id, '')) = '' then
    return jsonb_build_object('ok', false, 'error', 'invalid_family');
  end if;
  perform pg_advisory_xact_lock(hashtextextended(p_user_id::text || ':killgate-wallet', 0));

  insert into public.killgate_wallets(user_id)
  values (p_user_id)
  on conflict (user_id) do nothing;

  update public.killgate_wallets
     set subscription_credits = 0,
         subscription_credits_expire_at = null,
         updated_at = now()
   where user_id = p_user_id
     and subscription_credits_expire_at is not null
     and subscription_credits_expire_at <= now();

  select pass_id into v_pass_id
    from public.killgate_venture_passes
   where user_id = p_user_id
     and family_id = btrim(p_family_id)
     and credits_remaining > 0
     and (expires_at is null or expires_at > now())
   order by created_at, pass_id
   limit 1
   for update;

  if v_pass_id is not null then
    update public.killgate_venture_passes
       set credits_remaining = credits_remaining - 1
     where pass_id = v_pass_id;
    insert into public.killgate_credit_ledger(user_id, kind, amount, family_id, pass_id)
    values (p_user_id, 'debit_pass', -1, btrim(p_family_id), v_pass_id)
    returning id into v_debit_id;
    return jsonb_build_object('ok', true, 'source', 'venture_pass', 'pass_id', v_pass_id, 'debit_id', v_debit_id);
  end if;

  select subscription_credits, wallet_credits
    into v_subscription, v_wallet
    from public.killgate_wallets
   where user_id = p_user_id
   for update;

  if coalesce(v_subscription, 0) > 0 then
    update public.killgate_wallets
       set subscription_credits = subscription_credits - 1,
           updated_at = now()
     where user_id = p_user_id;
    insert into public.killgate_credit_ledger(user_id, kind, amount, family_id, period_id)
    select p_user_id, 'debit_subscription', -1, btrim(p_family_id), subscription_period_id
      from public.killgate_wallets where user_id = p_user_id
    returning id into v_debit_id;
    return jsonb_build_object('ok', true, 'source', 'subscription', 'debit_id', v_debit_id);
  end if;

  if coalesce(v_wallet, 0) > 0 then
    update public.killgate_wallets
       set wallet_credits = wallet_credits - 1,
           updated_at = now()
     where user_id = p_user_id;
    insert into public.killgate_credit_ledger(user_id, kind, amount, family_id)
    values (p_user_id, 'debit_wallet', -1, btrim(p_family_id))
    returning id into v_debit_id;
    return jsonb_build_object('ok', true, 'source', 'wallet', 'debit_id', v_debit_id);
  end if;

  return jsonb_build_object('ok', false, 'error', 'no_credits');
end;
$$;

create or replace function public.killgate_wallet_refund(
  p_user_id uuid,
  p_debit_id bigint
)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_debit public.killgate_credit_ledger%rowtype;
  v_subscription_expires_at timestamptz;
  v_refunded_to text;
begin
  if p_user_id is null or p_debit_id is null then
    raise exception 'user id and debit id are required' using errcode = '22023';
  end if;

  perform pg_advisory_xact_lock(hashtextextended(p_user_id::text || ':killgate-wallet', 0));

  if exists(
    select 1 from public.killgate_credit_ledger
     where user_id = p_user_id
       and kind = 'refund_research'
       and related_debit_id = p_debit_id
  ) then
    return jsonb_build_object('ok', true, 'duplicate', true, 'debit_id', p_debit_id);
  end if;

  select * into v_debit
    from public.killgate_credit_ledger
   where id = p_debit_id
     and user_id = p_user_id
     and kind in ('debit_pass', 'debit_subscription', 'debit_wallet')
   for update;

  if not found then
    raise exception 'research debit receipt was not found' using errcode = '22023';
  end if;

  insert into public.killgate_wallets(user_id)
  values (p_user_id)
  on conflict (user_id) do nothing;

  if v_debit.kind = 'debit_pass' then
    update public.killgate_venture_passes
       set credits_remaining = credits_remaining + 1
     where user_id = p_user_id
       and pass_id = v_debit.pass_id;
    if not found then
      raise exception 'venture pass for refund was not found' using errcode = '22023';
    end if;
    v_refunded_to := 'venture_pass';
  elsif v_debit.kind = 'debit_subscription' then
    select subscription_credits_expire_at into v_subscription_expires_at
      from public.killgate_wallets
     where user_id = p_user_id
     for update;
    if v_subscription_expires_at is not null and v_subscription_expires_at > now() then
      update public.killgate_wallets
         set subscription_credits = subscription_credits + 1, updated_at = now()
       where user_id = p_user_id;
      v_refunded_to := 'subscription';
    else
      update public.killgate_wallets
         set wallet_credits = wallet_credits + 1, updated_at = now()
       where user_id = p_user_id;
      v_refunded_to := 'wallet';
    end if;
  else
    update public.killgate_wallets
       set wallet_credits = wallet_credits + 1, updated_at = now()
     where user_id = p_user_id;
    v_refunded_to := 'wallet';
  end if;

  insert into public.killgate_credit_ledger(
    user_id, kind, amount, family_id, pass_id, related_debit_id
  ) values (
    p_user_id, 'refund_research', 1, v_debit.family_id, v_debit.pass_id, p_debit_id
  );

  return jsonb_build_object(
    'ok', true, 'duplicate', false, 'debit_id', p_debit_id, 'refunded_to', v_refunded_to
  );
end;
$$;

revoke all on function public.killgate_wallet_snapshot(uuid) from public, anon, authenticated;
revoke all on function public.killgate_wallet_grant(uuid, text, text, text, integer, integer, integer, integer, text, timestamptz, text, boolean) from public, anon, authenticated;
revoke all on function public.killgate_wallet_bind_pass(uuid, text, text) from public, anon, authenticated;
revoke all on function public.killgate_wallet_debit(uuid, text) from public, anon, authenticated;
revoke all on function public.killgate_wallet_refund(uuid, bigint) from public, anon, authenticated;

grant execute on function public.killgate_wallet_snapshot(uuid) to service_role;
grant execute on function public.killgate_wallet_grant(uuid, text, text, text, integer, integer, integer, integer, text, timestamptz, text, boolean) to service_role;
grant execute on function public.killgate_wallet_bind_pass(uuid, text, text) to service_role;
grant execute on function public.killgate_wallet_debit(uuid, text) to service_role;
grant execute on function public.killgate_wallet_refund(uuid, bigint) to service_role;
