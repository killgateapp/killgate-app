#!/usr/bin/env node
/* Real PostgreSQL transaction/permission checks. Only a disposable localhost
 * database is created; no Supabase account or production credentials are used.
 * Requires pg (test tooling only) and KILLGATE_TEST_DATABASE_URL pointing to a
 * local PostgreSQL maintenance database. Each run creates its own test database.
 */
const { Client } = require('pg');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const assert = require('node:assert/strict');

async function main() {
  const target = new URL(process.env.KILLGATE_TEST_DATABASE_URL || '');
  if (!['localhost', '127.0.0.1', '[::1]'].includes(target.hostname)) {
    throw new Error('Only a disposable localhost PostgreSQL instance is allowed.');
  }
  const database = `killgate_test_${randomUUID().replaceAll('-', '')}`;
  const maintenance = new Client({ connectionString: target.href });
  await maintenance.connect();
  const clients = [];
  let created = false;
  let checks = 0;
  const check = (name) => { checks += 1; process.stdout.write(`PASS ${name}\n`); };
  try {
    await maintenance.query(`create database "${database}"`);
    created = true;
    target.pathname = `/${database}`;
    for (let i = 0; i < 3; i++) {
      const client = new Client({ connectionString: target.href, statement_timeout: 15000 });
      await client.connect();
      clients.push(client);
    }
    const [db, first, second] = clients;
    await db.query(`
      do $$ begin create role anon nologin; exception when duplicate_object then null; end $$;
      do $$ begin create role authenticated nologin; exception when duplicate_object then null; end $$;
      do $$ begin create role service_role nologin bypassrls; exception when duplicate_object then null; end $$;
      create schema auth;
      create table auth.users(id uuid primary key);
      create function auth.uid() returns uuid language sql stable as
        $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
      grant usage on schema auth to authenticated;
      grant execute on function auth.uid() to authenticated;
      create extension if not exists pgcrypto;
    `);
    const order = [
      '20260824_killgate_single_user_accounts.sql',
      '20260824_killgate_venture_revisions.sql',
      '20260824_killgate_play_token_history.sql',
      '20260824_killgate_atomic_play_entitlement.sql',
      '20260824_killgate_ordered_play_entitlement.sql',
      '20260824_killgate_play_rtdn_events.sql',
      '20260824_killgate_distributed_rate_limits.sql',
      '20260824_killgate_pre_auth_rate_limits.sql',
      '20260824_killgate_research_quota.sql',
      '20260824_killgate_research_quota_reservations.sql',
      '20260828_killgate_credits_and_passes.sql',
      '20260828_killgate_founder_pro_wallet_rpc.sql',
      '20260828_killgate_research_quota_windows.sql',
      '20260830224035_release_correctness.sql',
    ];
    for (const filename of order) {
      await db.query('begin');
      try {
        await db.query(readFileSync(path.join(__dirname, '../supabase/migrations', filename), 'utf8'));
        await db.query('commit');
      } catch (error) { await db.query('rollback'); throw new Error(`Migration failed: ${filename}`, { cause: error }); }
    }
    check('all migration SQL executed');
    const user = randomUUID(), otherUser = randomUUID();
    await db.query('insert into auth.users(id) values ($1), ($2)', [user, otherUser]);
    await db.query('insert into public.killgate_wallets(user_id,wallet_credits) values($1,10),($2,10)', [user, otherUser]);
    await first.query('set role service_role');
    await second.query('set role service_role');
    const rpc = async (client, name, values) => (await client.query(
      `select public.${name}(${values.map((_, i) => `$${i + 1}`).join(',')}) as result`, values,
    )).rows[0].result;
    const debit = (client, run) => rpc(client, 'killgate_wallet_debit_once', [user, 'V-FAMILY', run]);
    const cancel = (client, run) => rpc(client, 'killgate_wallet_cancel_research', [user, run]);
    const balance = async () => Number((await db.query('select wallet_credits from public.killgate_wallets where user_id=$1', [user])).rows[0].wallet_credits);
    const run = randomUUID();
    const receipts = await Promise.all([debit(first, run), debit(second, run)]);
    assert.equal(receipts[0].debit_id, receipts[1].debit_id);
    assert.equal(await balance(), 9);
    assert.equal((await debit(first, run)).debit_id, receipts[0].debit_id);
    assert.equal(await balance(), 9);
    check('concurrent and lost-response debit retries charge once');
    await assert.rejects(rpc(first, 'killgate_wallet_debit_once', [user, 'V-OTHER', run]), { code: '22023' });
    await rpc(second, 'killgate_wallet_debit_once', [otherUser, 'V-FAMILY', run]);
    check('operation IDs are bound to one user and family');
    await Promise.all([cancel(first, run), cancel(second, run)]);
    assert.equal(await balance(), 10);
    assert.equal((await debit(first, run)).error, 'research_run_cancelled');
    const cancelledFirst = randomUUID();
    await cancel(first, cancelledFirst);
    assert.equal((await debit(second, cancelledFirst)).error, 'research_run_cancelled');
    assert.equal(await balance(), 10);
    check('refund once and cancellation before delayed debit');
    for (let i = 0; i < 10; i++) {
      const racingRun = randomUUID();
      await Promise.all([debit(first, racingRun), cancel(second, racingRun)]);
    }
    assert.equal(await balance(), 10);
    check('ten simultaneous debit/cancel races leave zero net charge');
    const quotaRun = randomUUID();
    const reserve = (client, id) => rpc(client, 'killgate_research_quota_reserve_once', [user, id, 1, 2, 2592000]);
    const reservations = await Promise.all([reserve(first, quotaRun), reserve(second, quotaRun)]);
    assert.equal(reservations[0], reservations[1]);
    assert.notEqual(reservations[0], null);
    assert.equal(await reserve(first, randomUUID()), null);
    await rpc(second, 'killgate_research_quota_release_run', [user, quotaRun]);
    assert.equal(await reserve(first, quotaRun), null);
    const quotaCancel = randomUUID();
    await rpc(second, 'killgate_research_quota_release_run', [user, quotaCancel]);
    assert.equal(await reserve(first, quotaCancel), null);
    assert.notEqual(await reserve(first, randomUUID()), null);
    check('quota retries, caps and cancellation tombstones');
    const expiry = new Date(Date.now() + 86400000 * 30).toISOString();
    const currentHash = 'a'.repeat(64), staleHash = 'b'.repeat(64);
    const persist = (hash, linked) => rpc(first, 'killgate_persist_play_entitlement', [user, 'killgate_founder_pro_monthly', hash, true, 'SUBSCRIPTION_STATE_ACTIVE', expiry, new Date().toISOString(), linked]);
    assert.equal(await persist(currentHash, null), true);
    assert.equal(await persist(staleHash, null), false);
    const grant = (hash) => rpc(second, 'killgate_wallet_grant', [user, 'killgate_founder_pro_monthly', 'subscription', hash, 9, 0, 0, 30, expiry, expiry, '', false]);
    assert.equal((await grant(staleHash)).error, 'stale_purchase_ignored');
    assert.equal((await grant(currentHash)).ok, true);
    const subscriptionRun = randomUUID();
    await debit(first, subscriptionRun);
    const replacementHash = 'c'.repeat(64);
    assert.equal(await persist(replacementHash, currentHash), true);
    assert.equal((await grant(currentHash)).error, 'stale_purchase_ignored');
    check('stale entitlement and accepted-then-replaced refill are rejected');
    await db.query("update public.killgate_wallets set subscription_period_id='new-period', subscription_credits=9 where user_id=$1", [user]);
    await cancel(first, subscriptionRun);
    const snapshot = (await db.query('select subscription_credits,wallet_credits from public.killgate_wallets where user_id=$1', [user])).rows[0];
    assert.equal(snapshot.subscription_credits, 9);
    assert.equal(snapshot.wallet_credits, 11);
    check('refund from an older subscription period becomes a wallet credit');
    const state = { storage_revision: 1, validation_contract: { status: 'locked' }, metrics: {} };
    const create = (client, id) => rpc(client, 'killgate_create_venture_with_slot', [user, id, state, new Date().toISOString()]);
    await create(first, 'V-ONE'); await create(first, 'V-TWO');
    const createdSlots = await Promise.all([create(first, 'V-THREE'), create(second, 'V-FOUR')]);
    assert.equal(createdSlots.filter(row => row.ok).length, 1);
    assert.equal(createdSlots.filter(row => row.error === 'slot_full').length, 1);
    check('concurrent creation admits only the third live root');
    // Free one slot; race two different archived rows for it.
    await db.query("update public.ventures set state=jsonb_set(state,'{metrics,archived_at}','\"archived\"') where user_id=$1 and id='V-ONE'", [user]);
    const archived = { ...state, metrics: { archived_at: 'archived' } };
    await db.query("insert into public.ventures(user_id,id,state,revision) values($1,'V-ARCHIVED',$2,1)", [user, archived]);
    const unarchive = (client, id, payload = state) => rpc(client, 'killgate_unarchive_venture_with_slot', [user, id, 1, payload, new Date().toISOString()]);
    const unarchived = await Promise.all([unarchive(first, 'V-ONE'), unarchive(second, 'V-ARCHIVED')]);
    assert.equal(unarchived.filter(row => row.ok).length, 1);
    assert.equal(unarchived.filter(row => row.error === 'slot_full').length, 1);
    check('concurrent unarchive admits only the remaining live root');
    const child = { ...state, metrics: { archived_at: 'archived', pivot_parent_venture_id: 'V-TWO' } };
    await db.query("insert into public.ventures(user_id,id,state,revision) values($1,'V-CHILD',$2,1)", [user, child]);
    delete child.metrics.archived_at;
    assert.equal((await unarchive(first, 'V-CHILD', child)).ok, true);
    await assert.rejects(db.query("insert into public.ventures(user_id,id,state) values($1,'V-BYPASS',$2)", [user, state]), { code: '23514' });
    check('pivot children use no new slot and direct writes cannot bypass the invariant');
    const abandoned = randomUUID();
    const pending = { ...child, metrics: { ...child.metrics, research_run_id: abandoned, research_run_status: 'pending', research_run_paid: true } };
    await db.query("insert into public.ventures(user_id,id,state,revision) values($1,'V-ABANDONED',$2,1)", [user, pending]);
    const beforeAbandonment = await balance();
    // Use wallet credits so the balance assertion is independent of the Pro tests.
    await db.query('update public.killgate_wallets set subscription_credits=0 where user_id=$1', [user]);
    await debit(first, abandoned);
    assert.equal((await rpc(first, 'killgate_reconcile_research_run', [user, 'V-ABANDONED', abandoned])).status, 'restored');
    assert.equal(await balance(), beforeAbandonment);
    assert.equal((await db.query("update public.ventures set state=$1 where user_id=$2 and id='V-ABANDONED' and revision=1 returning id", [pending, user])).rowCount, 0);
    assert.equal((await debit(first, abandoned)).error, 'research_run_cancelled');
    await assert.rejects(rpc(first, 'killgate_reconcile_research_run', [user, 'V-ABANDONED', randomUUID()]), { code: '22023' });
    await db.query("update public.ventures set state=jsonb_set(state,'{metrics,last_research}','\"RESEARCH_PASS\"') where user_id=$1 and id='V-ABANDONED'", [user]);
    assert.equal((await rpc(first, 'killgate_reconcile_research_run', [user, 'V-ABANDONED', abandoned])).status, 'delivered');
    check('abandoned-worker recovery fences late saves and preserves delivered results');
    const functions = (await db.query(`select p.oid::regprocedure::text as signature,
      has_function_privilege('anon',p.oid,'execute') as anon,
      has_function_privilege('authenticated',p.oid,'execute') as customer
      from pg_proc p join pg_namespace n on n.oid=p.pronamespace
      where n.nspname='public' and p.proname like 'killgate_%'`)).rows;
    assert(functions.length > 15);
    for (const func of functions) {
      assert.equal(func.anon, false, `${func.signature}: anonymous execution`);
      assert.equal(func.customer, false, `${func.signature}: customer execution`);
    }
    for (const name of ['killgate_wallet_debit_unkeyed(uuid,text)', 'killgate_wallet_grant_original(uuid,text,text,text,integer,integer,integer,integer,text,timestamp with time zone,text,boolean)', 'killgate_wallet_refund_original(uuid,bigint)']) {
      assert.equal((await db.query("select has_function_privilege('service_role',$1,'execute') as allowed", [name])).rows[0].allowed, false);
    }
    check('customer RPC denial and private implementation denial');
    process.stdout.write(`PostgreSQL release checks: ${checks} passed\n`);
  } finally {
    await Promise.allSettled(clients.map(client => client.end()));
    if (created) await maintenance.query(`drop database "${database}"`);
    await maintenance.end();
  }
}
main().catch(error => { process.stderr.write(`${error.message}\n${error.cause?.message || ''}\n`); process.exitCode = 1; });
