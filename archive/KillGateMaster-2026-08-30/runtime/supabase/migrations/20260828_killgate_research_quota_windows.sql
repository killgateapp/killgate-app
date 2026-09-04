-- Generalized research reservation window for the two-week beta policy.
-- The existing three-argument function remains available for older operators;
-- production runtime uses this function so beta and paid windows can differ.

create or replace function public.killgate_research_quota_reserve_window(
  p_user_id uuid,
  p_hourly_max integer,
  p_rolling_max integer,
  p_rolling_window_seconds integer
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
     or p_rolling_max < 1
     or p_rolling_max > 10000
     or p_rolling_window_seconds < 1
     or p_rolling_window_seconds > 2678400 then
    return null;
  end if;

  perform pg_advisory_xact_lock(
    hashtextextended(p_user_id::text || ':research-quota', 0)
  );

  delete from public.request_rate_events
   where user_id = p_user_id
     and bucket = 'research'
     and occurred_at <= now_at - make_interval(secs => p_rolling_window_seconds);

  select
    count(*) filter (where occurred_at > now_at - interval '1 hour'),
    count(*)
    into hourly_count, rolling_count
    from public.request_rate_events
   where user_id = p_user_id
     and bucket = 'research'
     and occurred_at > now_at - make_interval(secs => p_rolling_window_seconds);

  if hourly_count >= p_hourly_max or rolling_count >= p_rolling_max then
    return null;
  end if;

  insert into public.request_rate_events (user_id, bucket, occurred_at)
  values (p_user_id, 'research', now_at)
  returning id into event_id;

  return event_id;
end;
$$;

revoke all on function public.killgate_research_quota_reserve_window(uuid, integer, integer, integer) from public, anon, authenticated;
grant execute on function public.killgate_research_quota_reserve_window(uuid, integer, integer, integer) to service_role;
