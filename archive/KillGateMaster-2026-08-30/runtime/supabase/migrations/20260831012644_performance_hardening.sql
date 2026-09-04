-- Keep ownership checks constant per query instead of evaluating auth.uid()
-- for every candidate row under RLS.
alter policy killgate_wallets_select_own on public.killgate_wallets
  using ((select auth.uid()) = user_id);

alter policy killgate_passes_select_own on public.killgate_venture_passes
  using ((select auth.uid()) = user_id);

alter policy killgate_ledger_select_own on public.killgate_credit_ledger
  using ((select auth.uid()) = user_id);

-- Foreign-key cascade and per-owner pass lookups need an index on the owner.
create index if not exists killgate_venture_passes_user_id_idx
  on public.killgate_venture_passes(user_id);
