-- Apply before deploying the matching runtime. All new entry points are server-only.
-- Existing ledger rows remain intact. Run IDs/cancellation tombstones are retained.
alter table public.killgate_credit_ledger add column research_run_id uuid;
create unique index killgate_credit_ledger_research_run
  on public.killgate_credit_ledger(user_id, research_run_id)
  where research_run_id is not null;
alter table public.request_rate_events add column research_run_id uuid;
alter table public.request_rate_events add column released_at timestamptz;
create unique index request_rate_events_research_run
  on public.request_rate_events(user_id, research_run_id)
  where research_run_id is not null;

-- Keep the original debit implementation private and invoke it under the same
-- wallet lock as the idempotency lookup. There is no unkeyed server API afterward.
alter function public.killgate_wallet_debit(uuid, text) rename to killgate_wallet_debit_unkeyed;
revoke all on function public.killgate_wallet_debit_unkeyed(uuid, text) from public, anon, authenticated, service_role;

create function public.killgate_wallet_debit_once(p_user_id uuid, p_family_id text, p_research_run_id uuid)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  original public.killgate_credit_ledger%rowtype;
  receipt jsonb;
begin
  if p_user_id is null or p_research_run_id is null or btrim(coalesce(p_family_id, '')) = '' then
    raise exception 'user, family and research run are required' using errcode = '22023';
  end if;
  perform pg_advisory_xact_lock(hashtextextended(p_user_id::text || ':killgate-wallet', 0));
  select * into original from public.killgate_credit_ledger
    where user_id = p_user_id and research_run_id = p_research_run_id;
  if found then
    if original.kind = 'cancel_research' or exists (
      select 1 from public.killgate_credit_ledger where user_id = p_user_id
        and kind = 'refund_research' and related_debit_id = original.id
    ) then
      return jsonb_build_object('ok', false, 'error', 'research_run_cancelled');
    end if;
    if original.family_id is distinct from btrim(p_family_id) then
      raise exception 'research run family mismatch' using errcode = '22023';
    end if;
    return jsonb_build_object('ok', true, 'duplicate', true, 'debit_id', original.id,
      'source', case original.kind when 'debit_pass' then 'venture_pass'
                 when 'debit_subscription' then 'subscription' else 'wallet' end,
      'pass_id', original.pass_id);
  end if;
  receipt := public.killgate_wallet_debit_unkeyed(p_user_id, p_family_id);
  if receipt->>'ok' = 'true' then
    update public.killgate_credit_ledger set research_run_id = p_research_run_id
      where user_id = p_user_id and id = (receipt->>'debit_id')::bigint;
  end if;
  return receipt;
end;
$$;

create function public.killgate_wallet_cancel_research(p_user_id uuid, p_research_run_id uuid)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare original public.killgate_credit_ledger%rowtype;
begin
  if p_user_id is null or p_research_run_id is null then
    raise exception 'user and research run are required' using errcode = '22023';
  end if;
  perform pg_advisory_xact_lock(hashtextextended(p_user_id::text || ':killgate-wallet', 0));
  select * into original from public.killgate_credit_ledger
    where user_id = p_user_id and research_run_id = p_research_run_id;
  if found and original.kind <> 'cancel_research' then
    return public.killgate_wallet_refund(p_user_id, original.id);
  elsif not found then
    insert into public.killgate_credit_ledger(user_id, kind, amount, research_run_id)
      values (p_user_id, 'cancel_research', 0, p_research_run_id);
  end if;
  return jsonb_build_object('ok', true, 'cancelled', true);
end;
$$;

-- A subscription refund must not increase a newer period's allocation.
-- Reuse the existing receipt/refund logic, then transfer a cross-period refund
-- to ordinary wallet credit under the same transaction lock.
alter function public.killgate_wallet_refund(uuid, bigint) rename to killgate_wallet_refund_original;
revoke all on function public.killgate_wallet_refund_original(uuid, bigint) from public, anon, authenticated, service_role;
create function public.killgate_wallet_refund(p_user_id uuid, p_debit_id bigint)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare receipt jsonb; debit_period text; current_period text;
begin
  if p_user_id is null or p_debit_id is null then
    raise exception 'user and debit are required' using errcode = '22023';
  end if;
  perform pg_advisory_xact_lock(hashtextextended(p_user_id::text || ':killgate-wallet', 0));
  select period_id into debit_period from public.killgate_credit_ledger
    where user_id = p_user_id and id = p_debit_id and kind = 'debit_subscription';
  select subscription_period_id into current_period from public.killgate_wallets where user_id = p_user_id;
  receipt := public.killgate_wallet_refund_original(p_user_id, p_debit_id);
  if receipt->>'duplicate' = 'false' and receipt->>'refunded_to' = 'subscription'
     and debit_period is distinct from current_period then
    update public.killgate_wallets set subscription_credits = subscription_credits - 1,
      wallet_credits = wallet_credits + 1 where user_id = p_user_id;
    receipt := jsonb_set(receipt, '{refunded_to}', '"wallet"'::jsonb);
  end if;
  return receipt;
end;
$$;

-- Serialize the final refill check with ordered entitlement replacement. A true
-- persist result from an earlier transaction alone is not sufficient.
alter function public.killgate_wallet_grant(uuid, text, text, text, integer, integer, integer, integer, text, timestamptz, text, boolean)
  rename to killgate_wallet_grant_original;
revoke all on function public.killgate_wallet_grant_original(uuid, text, text, text, integer, integer, integer, integer, text, timestamptz, text, boolean)
  from public, anon, authenticated, service_role;
create function public.killgate_wallet_grant(
  p_user_id uuid, p_product_id text, p_product_kind text, p_purchase_hash text,
  p_wallet_credits integer, p_venture_passes integer, p_credits_per_pass integer,
  p_period_days integer, p_subscription_period_id text, p_subscription_expires_at timestamptz,
  p_family_id text, p_requires_active_subscription boolean
)
returns jsonb language plpgsql security definer set search_path = '' as $$
begin
  if p_user_id is null then
    raise exception 'user is required' using errcode = '22023';
  end if;
  if p_product_kind = 'subscription' then
    perform pg_advisory_xact_lock(hashtextextended(p_user_id::text || ':play-entitlement', 0));
    if not exists (select 1 from public.subscription_entitlements
      where user_id = p_user_id and product_id = p_product_id
        and purchase_token_hash = p_purchase_hash and active
        and expires_at = p_subscription_expires_at and expires_at > now()) then
      return jsonb_build_object('ok', false, 'error', 'stale_purchase_ignored');
    end if;
  end if;
  return public.killgate_wallet_grant_original(p_user_id, p_product_id, p_product_kind,
    p_purchase_hash, p_wallet_credits, p_venture_passes, p_credits_per_pass, p_period_days,
    p_subscription_period_id, p_subscription_expires_at, p_family_id, p_requires_active_subscription);
end;
$$;

create function public.killgate_research_quota_reserve_once(
  p_user_id uuid, p_research_run_id uuid, p_hourly_max integer,
  p_rolling_max integer, p_rolling_window_seconds integer
)
returns bigint language plpgsql security definer set search_path = '' as $$
declare existing public.request_rate_events%rowtype; event_id bigint;
begin
  if p_user_id is null or p_research_run_id is null or p_hourly_max is null or p_rolling_max is null
     or p_rolling_window_seconds is null or p_hourly_max not between 1 and 1000
     or p_rolling_max not between 1 and 10000 or p_rolling_window_seconds not between 1 and 2678400 then
    return null;
  end if;
  perform pg_advisory_xact_lock(hashtextextended(p_user_id::text || ':research-quota', 0));
  select * into existing from public.request_rate_events
    where user_id = p_user_id and research_run_id = p_research_run_id;
  if found then
    return case when existing.released_at is null then existing.id else null end;
  end if;
  if (select count(*) from public.request_rate_events where user_id = p_user_id and bucket = 'research'
        and released_at is null and occurred_at > now() - interval '1 hour') >= p_hourly_max
     or (select count(*) from public.request_rate_events where user_id = p_user_id and bucket = 'research'
        and released_at is null and occurred_at > now() - make_interval(secs => p_rolling_window_seconds)) >= p_rolling_max then
    return null;
  end if;
  insert into public.request_rate_events(user_id, bucket, research_run_id)
    values (p_user_id, 'research', p_research_run_id) returning id into event_id;
  return event_id;
end;
$$;

create function public.killgate_research_quota_release_run(p_user_id uuid, p_research_run_id uuid)
returns boolean language plpgsql security definer set search_path = '' as $$
begin
  if p_user_id is null or p_research_run_id is null then return false; end if;
  perform pg_advisory_xact_lock(hashtextextended(p_user_id::text || ':research-quota', 0));
  insert into public.request_rate_events(user_id, bucket, research_run_id, released_at)
    values (p_user_id, 'research', p_research_run_id, now())
    on conflict (user_id, research_run_id) where research_run_id is not null
    do update set released_at = coalesce(public.request_rate_events.released_at, excluded.released_at);
  return true;
end;
$$;

-- A single predicate is shared by admission RPCs and the all-write invariant.
create function public.killgate_is_live_root(p_state jsonb)
returns boolean language sql immutable set search_path = '' as $$
  select coalesce(p_state #>> '{validation_contract,status}', '') = 'locked'
    and coalesce(p_state #>> '{metrics,archived_at}', '') = ''
    and btrim(coalesce(p_state #>> '{metrics,pivot_parent_venture_id}', '')) = '';
$$;

create function public.killgate_enforce_live_slots()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if tg_op = 'UPDATE' and new.user_id is distinct from old.user_id then
    raise exception 'venture owner cannot change' using errcode = '23514';
  end if;
  perform pg_advisory_xact_lock(hashtextextended(new.user_id::text || ':live-slots', 0));
  -- Existing over-limit accounts remain editable; only new slot admission fails.
  if public.killgate_is_live_root(new.state) and
     (tg_op = 'INSERT' or not public.killgate_is_live_root(old.state)) then
    if (select count(*) from public.ventures where user_id = new.user_id
          and id <> new.id and public.killgate_is_live_root(state)) >= 3 then
      raise exception 'live slot limit reached' using errcode = '23514';
    end if;
  end if;
  return new;
end;
$$;
create trigger killgate_live_slot_invariant before insert or update on public.ventures
  for each row execute function public.killgate_enforce_live_slots();

create function public.killgate_create_venture_with_slot(
  p_user_id uuid, p_venture_id text, p_state jsonb, p_updated_at timestamptz
)
returns jsonb language plpgsql security definer set search_path = '' as $$
begin
  if p_user_id is null or p_state is null or not public.killgate_is_live_root(p_state) then
    raise exception 'user and locked root state are required' using errcode = '22023';
  end if;
  perform pg_advisory_xact_lock(hashtextextended(p_user_id::text || ':live-slots', 0));
  if exists(select 1 from public.ventures where user_id = p_user_id and id = p_venture_id) then
    return jsonb_build_object('ok', false, 'error', 'venture_exists');
  end if;
  if (select count(*) from public.ventures where user_id = p_user_id and public.killgate_is_live_root(state)) >= 3 then
    return jsonb_build_object('ok', false, 'error', 'slot_full');
  end if;
  insert into public.ventures(user_id, id, state, revision, updated_at)
    values(p_user_id, p_venture_id, jsonb_set(p_state, '{storage_revision}', '1'), 1, p_updated_at);
  return jsonb_build_object('ok', true);
end;
$$;

create function public.killgate_unarchive_venture_with_slot(
  p_user_id uuid, p_venture_id text, p_expected_revision integer, p_state jsonb, p_updated_at timestamptz
)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare current_row public.ventures%rowtype;
begin
  if p_user_id is null or p_state is null or p_expected_revision is null then
    raise exception 'user, revision and state are required' using errcode = '22023';
  end if;
  perform pg_advisory_xact_lock(hashtextextended(p_user_id::text || ':live-slots', 0));
  select * into current_row from public.ventures where user_id = p_user_id and id = p_venture_id for update;
  if not found then return jsonb_build_object('ok', false, 'error', 'not_found'); end if;
  if current_row.revision <> p_expected_revision then
    return jsonb_build_object('ok', false, 'error', 'revision_conflict');
  end if;
  if public.killgate_is_live_root(p_state) and not public.killgate_is_live_root(current_row.state)
     and (select count(*) from public.ventures where user_id = p_user_id
            and id <> p_venture_id and public.killgate_is_live_root(state)) >= 3 then
    return jsonb_build_object('ok', false, 'error', 'slot_full');
  end if;
  update public.ventures set state = jsonb_set(p_state, '{storage_revision}', to_jsonb(p_expected_revision + 1)),
    revision = p_expected_revision + 1, updated_at = p_updated_at
    where user_id = p_user_id and id = p_venture_id;
  return jsonb_build_object('ok', true);
end;
$$;

revoke all on function public.killgate_is_live_root(jsonb) from public, anon, authenticated;
revoke all on function public.killgate_enforce_live_slots() from public, anon, authenticated, service_role;
revoke all on function public.killgate_wallet_debit_once(uuid, text, uuid) from public, anon, authenticated;
revoke all on function public.killgate_wallet_cancel_research(uuid, uuid) from public, anon, authenticated;
revoke all on function public.killgate_wallet_refund(uuid, bigint) from public, anon, authenticated;
revoke all on function public.killgate_wallet_grant(uuid, text, text, text, integer, integer, integer, integer, text, timestamptz, text, boolean) from public, anon, authenticated;
revoke all on function public.killgate_research_quota_reserve_once(uuid, uuid, integer, integer, integer) from public, anon, authenticated;
revoke all on function public.killgate_research_quota_release_run(uuid, uuid) from public, anon, authenticated;
revoke all on function public.killgate_create_venture_with_slot(uuid, text, jsonb, timestamptz) from public, anon, authenticated;
revoke all on function public.killgate_unarchive_venture_with_slot(uuid, text, integer, jsonb, timestamptz) from public, anon, authenticated;
grant execute on function public.killgate_wallet_debit_once(uuid, text, uuid) to service_role;
grant execute on function public.killgate_wallet_cancel_research(uuid, uuid) to service_role;
grant execute on function public.killgate_wallet_refund(uuid, bigint) to service_role;
grant execute on function public.killgate_wallet_grant(uuid, text, text, text, integer, integer, integer, integer, text, timestamptz, text, boolean) to service_role;
grant execute on function public.killgate_research_quota_reserve_once(uuid, uuid, integer, integer, integer) to service_role;
grant execute on function public.killgate_research_quota_release_run(uuid, uuid) to service_role;
grant execute on function public.killgate_create_venture_with_slot(uuid, text, jsonb, timestamptz) to service_role;
grant execute on function public.killgate_unarchive_venture_with_slot(uuid, text, integer, jsonb, timestamptz) to service_role;

-- Operator recovery for an abandoned worker. The exact operation must match;
-- completed results are never refunded. The row revision fences a late result.
create function public.killgate_reconcile_research_run(p_user_id uuid, p_venture_id text, p_research_run_id uuid)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare current_row public.ventures%rowtype; revised jsonb;
begin
  if p_user_id is null or p_research_run_id is null or p_venture_id is null then
    raise exception 'user, venture and run are required' using errcode = '22023';
  end if;
  perform pg_advisory_xact_lock(hashtextextended(p_user_id::text || ':live-slots', 0));
  select * into current_row from public.ventures where user_id = p_user_id and id = p_venture_id for update;
  if not found or current_row.state #>> '{metrics,research_run_id}' is distinct from p_research_run_id::text then
    raise exception 'research operation mismatch' using errcode = '22023';
  end if;
  if coalesce(current_row.state #>> '{metrics,last_research}', '') <> '' then
    return jsonb_build_object('ok', true, 'status', 'delivered');
  end if;
  if current_row.state #>> '{metrics,research_run_paid}' = 'true' then
    perform public.killgate_wallet_cancel_research(p_user_id, p_research_run_id);
  end if;
  perform public.killgate_research_quota_release_run(p_user_id, p_research_run_id);
  revised := jsonb_set(current_row.state, '{metrics,research_run_status}', '"failed"');
  revised := jsonb_set(revised, '{storage_revision}', to_jsonb(current_row.revision + 1));
  update public.ventures set state = revised, revision = revision + 1, updated_at = now()
    where user_id = p_user_id and id = p_venture_id;
  return jsonb_build_object('ok', true, 'status', 'restored');
end;
$$;
revoke all on function public.killgate_reconcile_research_run(uuid, text, uuid) from public, anon, authenticated;
grant execute on function public.killgate_reconcile_research_run(uuid, text, uuid) to service_role;
