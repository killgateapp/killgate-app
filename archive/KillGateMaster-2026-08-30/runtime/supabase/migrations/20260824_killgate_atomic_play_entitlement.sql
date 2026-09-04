-- Persist the current Google Play entitlement and immutable purchase-token owner
-- history in one database transaction. Only the server service role may execute.

create or replace function public.killgate_persist_play_entitlement(
  p_user_id uuid,
  p_product_id text,
  p_purchase_token_hash text,
  p_active boolean,
  p_subscription_state text,
  p_expires_at timestamptz,
  p_verified_at timestamptz default now()
)
returns void
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_existing_owner uuid;
  v_existing_product text;
  v_verified_at timestamptz := coalesce(p_verified_at, now());
begin
  if p_user_id is null then
    raise exception 'user id is required' using errcode = '22023';
  end if;
  if p_product_id is null or btrim(p_product_id) = '' then
    raise exception 'product id is required' using errcode = '22023';
  end if;
  if p_subscription_state is null or btrim(p_subscription_state) = '' then
    raise exception 'subscription state is required' using errcode = '22023';
  end if;
  if p_purchase_token_hash is null or p_purchase_token_hash !~ '^[0-9a-f]{64}$' then
    raise exception 'invalid purchase token hash' using errcode = '22023';
  end if;

  -- Serialize ownership decisions for the same Play purchase token hash.
  perform pg_advisory_xact_lock(hashtextextended(p_purchase_token_hash, 0));

  select user_id, product_id
    into v_existing_owner, v_existing_product
  from public.play_purchase_token_owners
  where purchase_token_hash = p_purchase_token_hash
  for update;

  if found then
    if v_existing_owner <> p_user_id then
      raise exception 'purchase token is already associated with another account'
        using errcode = '23505';
    end if;
    if v_existing_product <> p_product_id then
      raise exception 'purchase token product cannot change'
        using errcode = '23514';
    end if;

    update public.play_purchase_token_owners
       set last_verified_at = greatest(last_verified_at, v_verified_at)
     where purchase_token_hash = p_purchase_token_hash;
  else
    insert into public.play_purchase_token_owners (
      purchase_token_hash, user_id, product_id, first_verified_at, last_verified_at
    ) values (
      p_purchase_token_hash, p_user_id, p_product_id, v_verified_at, v_verified_at
    );
  end if;

  insert into public.subscription_entitlements (
    user_id,
    product_id,
    purchase_token_hash,
    active,
    subscription_state,
    expires_at,
    last_verified_at
  ) values (
    p_user_id,
    p_product_id,
    p_purchase_token_hash,
    p_active,
    p_subscription_state,
    p_expires_at,
    v_verified_at
  )
  on conflict (user_id) do update set
    product_id = excluded.product_id,
    purchase_token_hash = excluded.purchase_token_hash,
    active = excluded.active,
    subscription_state = excluded.subscription_state,
    expires_at = excluded.expires_at,
    last_verified_at = excluded.last_verified_at;
end;
$$;

revoke all on function public.killgate_persist_play_entitlement(uuid, text, text, boolean, text, timestamptz, timestamptz) from public, anon, authenticated;
grant execute on function public.killgate_persist_play_entitlement(uuid, text, text, boolean, text, timestamptz, timestamptz) to service_role;
