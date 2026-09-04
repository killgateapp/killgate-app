-- Atomic research allowance: an hourly abuse cap plus a bounded rolling 30-day
-- included allowance so AI usage cannot silently destroy subscription margins.

create or replace function public.killgate_research_quota_allow(
  p_user_id uuid,
  p_hourly_max integer,
  p_rolling_30d_max integer
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  hourly_count integer;
  rolling_count integer;
  now_at timestamptz := now();
begin
  if p_user_id is null
     or p_hourly_max < 1
     or p_hourly_max > 1000
     or p_rolling_30d_max < 1
     or p_rolling_30d_max > 10000 then
    return false;
  end if;

  -- Serialize research usage per user across all app workers/instances.
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
    return false;
  end if;

  insert into public.request_rate_events (user_id, bucket, occurred_at)
  values (p_user_id, 'research', now_at);
  return true;
end;
$$;

revoke all on function public.killgate_research_quota_allow(uuid, integer, integer) from public;
revoke all on function public.killgate_research_quota_allow(uuid, integer, integer) from anon, authenticated;
grant execute on function public.killgate_research_quota_allow(uuid, integer, integer) to service_role;
