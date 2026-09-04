-- Additive worker ownership for durable Deep Research execution.
-- No customer role receives table or RPC access; workers act only through the
-- server-side service role after the application has authenticated the owner.
alter table public.deep_research_runs
  add column if not exists worker_lease_token uuid,
  add column if not exists worker_lease_expires_at timestamptz,
  add column if not exists worker_attempt_count integer not null default 0
    check (worker_attempt_count >= 0),
  add column if not exists queued_at timestamptz not null default now();

alter table public.deep_research_snapshots
  add column if not exists competitors jsonb not null default '[]'::jsonb,
  add column if not exists pricing_observations jsonb not null default '[]'::jsonb;

-- Snapshot materialization already occurs in the original checkpoint RPC. Add
-- the structured market export fields without changing existing columns or
-- historical snapshots.
create or replace function public.killgate_deep_research_run_checkpoint(
  p_user_id uuid,
  p_run_id uuid,
  p_expected_revision bigint,
  p_status text,
  p_checkpoint jsonb default '{}'::jsonb,
  p_cost_ledger jsonb default '{}'::jsonb,
  p_result jsonb default null,
  p_report jsonb default null,
  p_failure_reason text default ''
)
returns jsonb language plpgsql set search_path = '' as $$
declare current_row public.deep_research_runs%rowtype;
begin
  if p_user_id is null or p_run_id is null or p_expected_revision is null
     or btrim(coalesce(p_status, '')) = '' then
    raise exception 'user, run, revision and status are required' using errcode = '22023';
  end if;
  if p_status not in ('queued', 'planning', 'retrieving', 'extracting', 'synthesizing',
                      'evaluating', 'completed', 'failed', 'cancelled') then
    raise exception 'invalid research run status' using errcode = '22023';
  end if;
  select * into current_row from public.deep_research_runs
    where run_id = p_run_id and user_id = p_user_id for update;
  if not found then return jsonb_build_object('ok', false, 'error', 'not_found'); end if;
  if current_row.status in ('completed', 'failed', 'cancelled') then
    return jsonb_build_object('ok', false, 'error', 'immutable_terminal', 'revision', current_row.revision, 'status', current_row.status);
  end if;
  if current_row.revision <> p_expected_revision then
    return jsonb_build_object('ok', false, 'error', 'revision_conflict', 'revision', current_row.revision);
  end if;
  update public.deep_research_runs set
    status = p_status, revision = revision + 1,
    evidence_set_fingerprint = coalesce(p_checkpoint ->> 'evidence_set_fingerprint', evidence_set_fingerprint),
    checkpoint = coalesce(p_checkpoint, '{}'::jsonb), cost_ledger = coalesce(p_cost_ledger, '{}'::jsonb),
    result = coalesce(p_result, result), report = coalesce(p_report, report),
    failure_reason = coalesce(p_failure_reason, ''), updated_at = now()
  where run_id = p_run_id and user_id = p_user_id;
  select * into current_row from public.deep_research_runs where run_id = p_run_id;
  if p_status = 'completed' then
    insert into public.deep_research_snapshots(
      research_run_id, user_id, venture_id, venture_family_id, validation_contract_fingerprint,
      hypothesis_fingerprint, previous_run_id, evidence_set_fingerprint, research_date, completed_at,
      research_config_version, prompt_protocol_version, models_used, budget_config, plan, evidence,
      competitors, pricing_observations, result, cost_ledger, report
    ) values (
      p_run_id, current_row.user_id, current_row.venture_id, current_row.venture_family_id,
      current_row.validation_contract_fingerprint, current_row.hypothesis_fingerprint, current_row.previous_run_id,
      current_row.evidence_set_fingerprint, current_row.created_at, current_row.updated_at,
      coalesce(current_row.checkpoint ->> 'research_config_version', '1'),
      coalesce(current_row.checkpoint ->> 'prompt_protocol_version', '1'),
      coalesce(current_row.checkpoint -> 'models_used', '[]'::jsonb),
      coalesce(current_row.checkpoint -> 'budget', '{}'::jsonb), current_row.checkpoint -> 'plan',
      coalesce(current_row.checkpoint -> 'sources', '[]'::jsonb),
      coalesce(current_row.checkpoint -> 'competitors', '[]'::jsonb),
      coalesce(current_row.checkpoint -> 'pricing_observations', '[]'::jsonb),
      current_row.result, current_row.cost_ledger, current_row.report
    ) on conflict (research_run_id) do nothing;
  end if;
  select * into current_row from public.deep_research_runs where run_id = p_run_id;
  return jsonb_build_object('ok', true, 'duplicate', false, 'run', to_jsonb(current_row));
end;
$$;

-- A venture can have one unfinished run.  Terminal snapshots remain available
-- for legitimate reruns through a new run ID and previous_run_id lineage.
create unique index if not exists deep_research_one_active_run_per_venture
  on public.deep_research_runs (user_id, venture_id)
  where status in ('queued', 'planning', 'retrieving', 'extracting', 'synthesizing', 'evaluating');

-- Claim is compare-and-set-like: a worker may claim an unleased run, renew its
-- own lease, or take over only after an expired lease.  It never changes a
-- terminal snapshot or bypasses user ownership.
create or replace function public.killgate_deep_research_run_claim(
  p_user_id uuid,
  p_run_id uuid,
  p_lease_token uuid,
  p_lease_seconds integer default 300
)
returns jsonb language plpgsql set search_path = '' as $$
declare current_row public.deep_research_runs%rowtype;
begin
  if p_user_id is null or p_run_id is null or p_lease_token is null
     or p_lease_seconds < 30 or p_lease_seconds > 3600 then
    raise exception 'user, run, lease token and bounded lease duration are required' using errcode = '22023';
  end if;
  select * into current_row from public.deep_research_runs
    where run_id = p_run_id and user_id = p_user_id for update;
  if not found then
    return jsonb_build_object('ok', false, 'error', 'not_found');
  end if;
  if current_row.status in ('completed', 'failed', 'cancelled') then
    return jsonb_build_object('ok', false, 'error', 'terminal', 'status', current_row.status);
  end if;
  if current_row.worker_lease_token is not null
     and current_row.worker_lease_token <> p_lease_token
     and current_row.worker_lease_expires_at > now() then
    return jsonb_build_object('ok', false, 'error', 'leased', 'status', current_row.status);
  end if;
  update public.deep_research_runs
     set worker_lease_token = p_lease_token,
         worker_lease_expires_at = now() + make_interval(secs => p_lease_seconds),
         worker_attempt_count = worker_attempt_count + 1,
         updated_at = now()
   where run_id = p_run_id and user_id = p_user_id;
  select * into current_row from public.deep_research_runs where run_id = p_run_id;
  return jsonb_build_object('ok', true, 'run', to_jsonb(current_row));
end;
$$;

create or replace function public.killgate_deep_research_run_release(
  p_user_id uuid,
  p_run_id uuid,
  p_lease_token uuid
)
returns boolean language plpgsql set search_path = '' as $$
begin
  if p_user_id is null or p_run_id is null or p_lease_token is null then
    raise exception 'user, run and lease token are required' using errcode = '22023';
  end if;
  update public.deep_research_runs
     set worker_lease_token = null,
         worker_lease_expires_at = null,
         updated_at = now()
   where run_id = p_run_id and user_id = p_user_id
     and worker_lease_token = p_lease_token
     and status not in ('completed', 'failed', 'cancelled');
  return found;
end;
$$;

revoke all on function public.killgate_deep_research_run_claim(uuid, uuid, uuid, integer)
  from public, anon, authenticated;
revoke all on function public.killgate_deep_research_run_release(uuid, uuid, uuid)
  from public, anon, authenticated;
grant execute on function public.killgate_deep_research_run_claim(uuid, uuid, uuid, integer)
  to service_role;
grant execute on function public.killgate_deep_research_run_release(uuid, uuid, uuid)
  to service_role;
