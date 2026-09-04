-- Durable, server-only state for bounded Deep Research runs.
-- This is additive: existing venture JSON, wallet ledgers, and quota tables
-- remain the source of truth for their respective concerns.
create table if not exists public.deep_research_runs (
  run_id uuid primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  venture_id text not null,
  venture_family_id text not null,
  validation_contract_fingerprint text not null check (validation_contract_fingerprint ~ '^[0-9a-f]{64}$'),
  hypothesis_fingerprint text not null check (hypothesis_fingerprint ~ '^[0-9a-f]{64}$'),
  previous_run_id uuid references public.deep_research_runs(run_id),
  evidence_set_fingerprint text not null default '' check (evidence_set_fingerprint = '' or evidence_set_fingerprint ~ '^[0-9a-f]{64}$'),
  status text not null default 'queued' check (status in (
    'queued', 'planning', 'retrieving', 'extracting', 'synthesizing',
    'evaluating', 'completed', 'failed', 'cancelled'
  )),
  revision bigint not null default 0 check (revision >= 0),
  checkpoint jsonb not null default '{}'::jsonb,
  cost_ledger jsonb not null default '{}'::jsonb,
  result jsonb not null default '{}'::jsonb,
  report jsonb not null default '{}'::jsonb,
  failure_reason text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.deep_research_runs enable row level security;
revoke all on table public.deep_research_runs from public, anon, authenticated;
grant select, insert, update on table public.deep_research_runs to service_role;
create index if not exists deep_research_runs_user_venture_idx
  on public.deep_research_runs (user_id, venture_id, created_at desc);
create index if not exists deep_research_runs_family_idx
  on public.deep_research_runs (user_id, venture_family_id, created_at desc);

-- A completed run is copied once into this append-only export surface. The
-- mutable run row remains useful for checkpoints; this table is the durable
-- ResearchSnapshot required for rerun comparison and customer export.
create table if not exists public.deep_research_snapshots (
  research_run_id uuid primary key references public.deep_research_runs(run_id) on delete restrict,
  user_id uuid not null references auth.users(id) on delete cascade,
  venture_id text not null,
  venture_family_id text not null,
  validation_contract_fingerprint text not null check (validation_contract_fingerprint ~ '^[0-9a-f]{64}$'),
  hypothesis_fingerprint text not null check (hypothesis_fingerprint ~ '^[0-9a-f]{64}$'),
  previous_run_id uuid references public.deep_research_runs(run_id),
  evidence_set_fingerprint text not null default '' check (evidence_set_fingerprint = '' or evidence_set_fingerprint ~ '^[0-9a-f]{64}$'),
  research_date timestamptz not null,
  completed_at timestamptz not null,
  research_config_version text not null default '1',
  prompt_protocol_version text not null default '1',
  models_used jsonb not null default '[]'::jsonb,
  budget_config jsonb not null default '{}'::jsonb,
  plan jsonb,
  evidence jsonb not null default '[]'::jsonb,
  result jsonb not null default '{}'::jsonb,
  cost_ledger jsonb not null default '{}'::jsonb,
  report jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

alter table public.deep_research_snapshots enable row level security;
revoke all on table public.deep_research_snapshots from public, anon, authenticated;
grant select on table public.deep_research_snapshots to service_role;
create index if not exists deep_research_snapshots_user_idx
  on public.deep_research_snapshots (user_id, venture_family_id, completed_at desc);

-- Create is idempotent for worker retries. A reused run ID with different
-- identity is rejected rather than silently changing ownership or hypothesis.
create or replace function public.killgate_deep_research_run_create(
  p_user_id uuid,
  p_run_id uuid,
  p_venture_id text,
  p_venture_family_id text,
  p_validation_contract_fingerprint text,
  p_hypothesis_fingerprint text,
  p_previous_run_id uuid default null,
  p_research_config_version text default '1',
  p_prompt_protocol_version text default '1',
  p_checkpoint jsonb default '{}'::jsonb
)
returns jsonb language plpgsql set search_path = '' as $$
declare existing_row public.deep_research_runs%rowtype;
begin
  if p_user_id is null or p_run_id is null or btrim(coalesce(p_venture_id, '')) = ''
     or btrim(coalesce(p_venture_family_id, '')) = ''
     or p_validation_contract_fingerprint is null
     or p_hypothesis_fingerprint is null then
    raise exception 'user, run, venture, family and fingerprints are required' using errcode = '22023';
  end if;
  select * into existing_row from public.deep_research_runs where run_id = p_run_id for update;
  if found then
    if existing_row.user_id <> p_user_id
       or existing_row.venture_id <> p_venture_id
       or existing_row.venture_family_id <> p_venture_family_id
       or existing_row.validation_contract_fingerprint <> p_validation_contract_fingerprint
       or existing_row.hypothesis_fingerprint <> p_hypothesis_fingerprint then
      raise exception 'research run identity conflict' using errcode = '23514';
    end if;
    return jsonb_build_object('ok', true, 'duplicate', true, 'run', to_jsonb(existing_row));
  end if;
  insert into public.deep_research_runs(
    run_id, user_id, venture_id, venture_family_id,
    validation_contract_fingerprint, hypothesis_fingerprint, previous_run_id,
    evidence_set_fingerprint, checkpoint
  ) values (
    p_run_id, p_user_id, p_venture_id, p_venture_family_id,
    p_validation_contract_fingerprint, p_hypothesis_fingerprint, p_previous_run_id,
    coalesce(p_checkpoint ->> 'evidence_set_fingerprint', ''),
    jsonb_build_object(
      'research_config_version', p_research_config_version,
      'prompt_protocol_version', p_prompt_protocol_version,
      'data', coalesce(p_checkpoint, '{}'::jsonb)
    )
  );
  select * into existing_row from public.deep_research_runs where run_id = p_run_id;
  return jsonb_build_object('ok', true, 'duplicate', false, 'run', to_jsonb(existing_row));
end;
$$;

-- Optimistic revision fencing makes a delayed worker unable to overwrite a
-- newer checkpoint. The server-only RPC is safe to retry with the same input.
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
  if not found then
    return jsonb_build_object('ok', false, 'error', 'not_found');
  end if;
  -- A terminal run is a ResearchSnapshot. It must never be rewritten by a
  -- delayed worker or a replayed provider response. Reruns create a new run
  -- ID and point back to this snapshot through previous_run_id.
  if current_row.status in ('completed', 'failed', 'cancelled') then
    return jsonb_build_object(
      'ok', false,
      'error', 'immutable_terminal',
      'revision', current_row.revision,
      'status', current_row.status
    );
  end if;
  if current_row.revision <> p_expected_revision then
    return jsonb_build_object('ok', false, 'error', 'revision_conflict', 'revision', current_row.revision);
  end if;
  update public.deep_research_runs
     set status = p_status,
         revision = revision + 1,
         evidence_set_fingerprint = coalesce(p_checkpoint ->> 'evidence_set_fingerprint', evidence_set_fingerprint),
         checkpoint = coalesce(p_checkpoint, '{}'::jsonb),
         cost_ledger = coalesce(p_cost_ledger, '{}'::jsonb),
         result = coalesce(p_result, result),
         report = coalesce(p_report, report),
         failure_reason = coalesce(p_failure_reason, ''),
         updated_at = now()
   where run_id = p_run_id and user_id = p_user_id;
  select * into current_row from public.deep_research_runs where run_id = p_run_id;
  if p_status = 'completed' then
    insert into public.deep_research_snapshots(
      research_run_id, user_id, venture_id, venture_family_id,
      validation_contract_fingerprint, hypothesis_fingerprint, previous_run_id,
      evidence_set_fingerprint, research_date, completed_at,
      research_config_version, prompt_protocol_version, models_used,
      budget_config, plan, evidence, result, cost_ledger, report
    ) values (
      p_run_id, current_row.user_id, current_row.venture_id, current_row.venture_family_id,
      current_row.validation_contract_fingerprint, current_row.hypothesis_fingerprint,
      current_row.previous_run_id, current_row.evidence_set_fingerprint,
      current_row.created_at, current_row.updated_at,
      coalesce(current_row.checkpoint ->> 'research_config_version', '1'),
      coalesce(current_row.checkpoint ->> 'prompt_protocol_version', '1'),
      coalesce(current_row.checkpoint -> 'models_used', '[]'::jsonb),
      coalesce(current_row.checkpoint -> 'budget', '{}'::jsonb),
      current_row.checkpoint -> 'plan',
      coalesce(current_row.checkpoint -> 'sources', '[]'::jsonb),
      current_row.result, current_row.cost_ledger, current_row.report
    ) on conflict (research_run_id) do nothing;
  end if;
  select * into current_row from public.deep_research_runs where run_id = p_run_id;
  return jsonb_build_object('ok', true, 'duplicate', false, 'run', to_jsonb(current_row));
end;
$$;

revoke all on function public.killgate_deep_research_run_create(uuid, uuid, text, text, text, text, uuid, text, text, jsonb)
  from public, anon, authenticated;
revoke all on function public.killgate_deep_research_run_checkpoint(uuid, uuid, bigint, text, jsonb, jsonb, jsonb, jsonb, text)
  from public, anon, authenticated;
grant execute on function public.killgate_deep_research_run_create(uuid, uuid, text, text, text, text, uuid, text, text, jsonb)
  to service_role;
grant execute on function public.killgate_deep_research_run_checkpoint(uuid, uuid, bigint, text, jsonb, jsonb, jsonb, jsonb, text)
  to service_role;
