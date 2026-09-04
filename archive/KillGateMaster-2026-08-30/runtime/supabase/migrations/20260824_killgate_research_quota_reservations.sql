-- Reservable research quota. Failed provider/search attempts can release their
-- included-usage reservation without letting clients manipulate the ledger.

create or replace function public.killgate_research_quota_reserve(
  p_user_id uuid,
  p_hourly_max integer,
  p_rolling_30d_max integer
)
returns bigint
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  hourly_count integer;
  rolling_count integer;
  now_at timestamptz := now();
  event_id bigint;
begin
  if p_user_id is null
     or p_hourly_max < 1
     or p_hourly_max > 1000
     or p_rolling_30d_max < 1
     or p_rolling_30d_max > 10000 then
    return null;
  end if;

  perform pg_advisory_xact_lock(
    hashtextextended(p_user_id::text || ':research-quota', 0)
  );

  delete from public.request_rate_events
   where user_id = p_user_id
     and bucket = 'research'
     and occurred_at <= now_at - interval '30 days';

  select
    count(*) filter (where occurred_at > now_at - interval '1 hour'),
    count(*)
    into hourly_count, rolling_count
    from public.request_rate_events
   where user_id = p_user_id
     and bucket = 'research'
     and occurred_at > now_at - interval '30 days';

  if hourly_count >= p_hourly_max or rolling_count >= p_rolling_30d_max then
    return null;
  end if;

  insert into public.request_rate_events (user_id, bucket, occurred_at)
  values (p_user_id, 'research', now_at)
  returning id into event_id;

  return event_id;
end;
$$;

create or replace function public.killgate_research_quota_release(
  p_user_id uuid,
  p_event_id bigint
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  deleted_count integer;
begin
  if p_user_id is null or p_event_id is null or p_event_id < 1 then
    return false;
  end if;

  perform pg_advisory_xact_lock(
    hashtextextended(p_user_id::text || ':research-quota', 0)
  );

  delete from public.request_rate_events
   where id = p_event_id
     and user_id = p_user_id
     and bucket = 'research';
  get diagnostics deleted_count = row_count;
  return deleted_count = 1;
end;
$$;

revoke all on function public.killgate_research_quota_reserve(uuid, integer, integer) from public, anon, authenticated;
revoke all on function public.killgate_research_quota_release(uuid, bigint) from public, anon, authenticated;
grant execute on function public.killgate_research_quota_reserve(uuid, integer, integer) to service_role;
grant execute on function public.killgate_research_quota_release(uuid, bigint) to service_role;
