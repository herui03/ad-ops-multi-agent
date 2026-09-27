// Chromium end-to-end run against the REAL backend process (uvicorn), serving the built UI.
//
// It starts/kills/restarts the server itself so restart and crash recovery are real process events,
// not mocks. Screenshots -> docs/screenshots/, results -> docs/evidence/e2e/results.json.
//
//   cd frontend && npm ci && npm run build && cd ..
//   NODE_PATH=$(npm root -g) PYTHON=python3 node e2e/run_e2e.mjs
//
// Needs the `playwright` npm package (global or local) and a Chromium it can launch.
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SHOTS = path.join(ROOT, 'docs', 'screenshots');
const OUT = path.join(ROOT, 'docs', 'evidence', 'e2e');
const PORT = Number(process.env.E2E_PORT || 8765);
const BASE = `http://127.0.0.1:${PORT}`;
const PY = process.env.PYTHON || 'python3';
const DATA = fs.mkdtempSync(path.join(os.tmpdir(), 'adops-e2e-'));
fs.mkdirSync(SHOTS, { recursive: true });
fs.mkdirSync(OUT, { recursive: true });

const results = [];
const consoleLog = [];
let server = null;
let serverDownWindow = false;
let expectedHttpError = null;   // label of a deliberate negative step (403/422 expected)

function record(name, pass, details = {}) {
  results.push({ name, pass, ...details });
  console.log(`${pass ? 'PASS' : 'FAIL'}  ${name}${details.note ? ' — ' + details.note : ''}`);
}

async function startServer(extraEnv = {}) {
  server = spawn(PY, ['-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', String(PORT)], {
    cwd: ROOT, env: { ...process.env, LLM_PROVIDER: 'demo', DATA_DIR: DATA, GROQ_API_KEY: '', ...extraEnv },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  server.stdout.on('data', () => {});
  server.stderr.on('data', () => {});
  for (let i = 0; i < 100; i++) {
    try { if ((await fetch(`${BASE}/health`)).ok) { serverDownWindow = false; return; } } catch { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error('server did not start');
}

async function killServer(signal = 'SIGKILL') {
  if (!server) return;
  serverDownWindow = true;
  const exited = new Promise((r) => server.once('exit', r));
  if (server.exitCode === null) server.kill(signal);
  await exited;
  server = null;
}

async function waitServerExit(timeoutMs = 5000) {
  const t0 = Date.now();
  while (server && server.exitCode === null && Date.now() - t0 < timeoutMs) await new Promise((r) => setTimeout(r, 50));
  const code = server?.exitCode;
  serverDownWindow = true;
  server = null;
  return code;
}

async function apiGet(p) { return (await fetch(`${BASE}${p}`)).json(); }

async function overflow(page) {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
}

async function shot(page, name) {
  const file = path.join(SHOTS, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  return path.relative(ROOT, file);
}

async function setRole(page, role) { await page.getByTestId('role-select').selectOption(role); }

async function submit(page, text, fault) {
  await setRole(page, 'requester');
  await page.getByTestId('nav-runs').click();
  await page.getByTestId('request-input').fill(text);
  if (fault) {
    await page.locator('summary', { hasText: 'Demo fault injection' }).click();
    await page.getByTestId('fault-kind').selectOption(fault);
  }
  const previous = new URL(page.url()).searchParams.get('run');
  await page.getByTestId('submit-request').click();
  await page.waitForFunction((prev) => {
    const cur = new URLSearchParams(location.search).get('run');
    return cur && cur !== prev;
  }, previous);
  const runId = new URL(page.url()).searchParams.get('run');
  await page.getByTestId('run-detail').filter({ hasText: runId }).waitFor();
  if (fault) {
    await page.getByTestId('fault-kind').selectOption('');
  }
  return runId;
}

async function waitStatus(page, status, timeout = 15000) {
  await page.getByTestId('run-status').filter({ hasText: status.replaceAll('_', ' ') }).waitFor({ timeout });
}

async function main() {
  await startServer();
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1366, height: 900 } });
  const page = await ctx.newPage();
  let dialogs = 0;
  page.on('dialog', async (d) => { dialogs += 1; await d.dismiss(); });
  page.on('console', (m) => { if (m.type() === 'error') consoleLog.push({ text: m.text(), duringServerDown: serverDownWindow, expectedNegativeStep: expectedHttpError }); });
  page.on('pageerror', (e) => consoleLog.push({ text: `pageerror: ${e.message}`, duringServerDown: serverDownWindow }));

  await page.goto(BASE);
  // wait for /api/meta to load; before that the badge shows a placeholder
  await page.getByTestId('mode-badge').filter({ hasText: /DEMO|LIVE/ }).waitFor();
  const badge = await page.getByTestId('mode-badge').innerText();
  record('ui loads in demo mode with explicit label', badge.includes('DEMO'), { note: badge });

  // 1. approval path
  const r1 = await submit(page, 'Plan a year-end campaign for Harbourlight Hotel with a S$80,000 budget');
  await waitStatus(page, 'awaiting_approval');
  let d1 = await apiGet(`/api/runs/${r1}`);
  const s1 = await shot(page, '01-awaiting-approval');
  record('gate pauses with zero actions', d1.status === 'awaiting_approval' && d1.actions.length === 0 &&
    d1.checkpoint.next_nodes[0] === 'approval_gate', { run_id: r1, screenshot: s1 });
  // requester tries to approve -> server-side 403 shown in the UI
  expectedHttpError = 'requester approves (expect 403)';
  await page.getByTestId('approve-btn').click();
  await page.getByTestId('action-error').waitFor();
  expectedHttpError = null;
  const denied = await page.getByTestId('action-error').innerText();
  const s1b = await shot(page, '02-role-denied');
  d1 = await apiGet(`/api/runs/${r1}`);
  record('wrong demo role is refused by the server', denied.includes('role_not_permitted') && d1.actions.length === 0,
    { note: denied.slice(0, 80), screenshot: s1b });
  await setRole(page, 'approver');
  await page.getByTestId('decision-comment').fill('Approved for the year-end test =SUM(1,2)');
  await page.getByTestId('approve-btn').dblclick();   // double click: same idempotency key
  await waitStatus(page, 'completed');
  await page.getByTestId('action-receipt').waitFor();
  d1 = await apiGet(`/api/runs/${r1}`);
  const s1c = await shot(page, '03-approved-simulated-action');
  record('approve executes exactly one simulated action (double click)', d1.status === 'completed' && d1.actions.length === 1 &&
    d1.decisions.length === 1, { screenshot: s1c, note: `actions=${d1.actions.length} decisions=${d1.decisions.length}` });

  // 2. rejection
  const r2 = await submit(page, 'Plan a spring campaign for Harbourlight Hotel with a S$30,000 budget');
  await waitStatus(page, 'awaiting_approval');
  await setRole(page, 'approver');
  await page.getByTestId('reject-btn').click();
  await waitStatus(page, 'rejected');
  const d2 = await apiGet(`/api/runs/${r2}`);
  const s2 = await shot(page, '04-rejected');
  record('reject is terminal with zero actions', d2.status === 'rejected' && d2.actions.length === 0 &&
    (await page.getByTestId('decision-panel').count()) === 0, { run_id: r2, screenshot: s2 });

  // 3. policy block + revise + approve
  const r3 = await submit(page, 'Launch a campaign saying Harbourlight Hotel is the best harbour view, S$40,000');
  await waitStatus(page, 'awaiting_approval');
  await setRole(page, 'approver');
  await page.getByTestId('blockers').waitFor();
  expectedHttpError = 'approve a blocked proposal (expect 422)';
  await page.getByTestId('approve-btn').click();
  await page.getByTestId('action-error').waitFor();
  expectedHttpError = null;
  const blockedMsg = await page.getByTestId('action-error').innerText();
  const s3a = await shot(page, '05-blocked-by-compliance');
  await page.locator('summary', { hasText: 'Request a revision' }).click();
  await page.getByTestId('remove-cr_b2').check();
  await page.getByTestId('revise-btn').click();
  await page.getByText('Proposal · revision 2').waitFor();
  const d3mid = await apiGet(`/api/runs/${r3}`);
  await page.getByTestId('approve-btn').click();
  await waitStatus(page, 'completed');
  const d3 = await apiGet(`/api/runs/${r3}`);
  const s3b = await shot(page, '06-revised-then-approved');
  record('blocked proposal refused, revision 2 approved', blockedMsg.includes('proposal_not_approvable') &&
    d3mid.proposals.length === 2 && d3.actions.length === 1 && d3.actions[0].revision === 2,
  { run_id: r3, screenshots: [s3a, s3b] });

  // 4. restart while pending (real process kill)
  const r4 = await submit(page, 'Plan a campaign for Harbourlight Hotel with a S$25,000 budget');
  await waitStatus(page, 'awaiting_approval');
  const before = await apiGet(`/api/runs/${r4}`);
  await killServer('SIGKILL');
  await page.getByTestId('socket-state').filter({ hasText: 'reconnecting' }).waitFor({ timeout: 10000 });
  const s4a = await shot(page, '07-server-killed-while-pending');
  await startServer();
  await page.getByTestId('socket-state').filter({ hasText: 'live' }).waitFor({ timeout: 20000 });
  const afterRestart = await apiGet(`/api/runs/${r4}`);
  await setRole(page, 'approver');
  await page.getByTestId('approve-btn').click();
  await waitStatus(page, 'completed');
  const d4 = await apiGet(`/api/runs/${r4}`);
  const s4b = await shot(page, '08-approved-after-restart');
  record('pending run survives process kill and resumes the same thread', afterRestart.status === 'awaiting_approval' &&
    afterRestart.checkpoint.thread_id === before.checkpoint.thread_id && d4.actions.length === 1,
  { run_id: r4, screenshots: [s4a, s4b] });

  // 5. crash right after the ledger commit, then Recover (replay protection)
  const r5 = await submit(page, 'Plan a campaign for Harbourlight Hotel with a S$15,000 budget');
  await waitStatus(page, 'awaiting_approval');
  await killServer('SIGTERM');
  await startServer({ DEMO_CRASH_POINT: 'after_commit' });
  await page.getByTestId('socket-state').filter({ hasText: 'live' }).waitFor({ timeout: 20000 });
  await setRole(page, 'approver');
  serverDownWindow = true;   // the server is configured to die during this request
  await page.getByTestId('approve-btn').click();
  const exitCode = await waitServerExit();
  await page.getByTestId('action-error').waitFor({ timeout: 10000 });
  const s5a = await shot(page, '09-server-crashed-after-commit');
  await startServer();   // no crash point this time
  await page.reload();
  await waitStatus(page, 'interrupted');
  const s5b = await shot(page, '10-interrupted-after-crash');
  await setRole(page, 'approver');
  await page.getByTestId('recover-run').click();
  await waitStatus(page, 'completed');
  await page.getByTestId('replay-note').waitFor();
  const d5 = await apiGet(`/api/runs/${r5}`);
  const s5c = await shot(page, '11-recovered-replay-detected');
  record('crash after commit: recover reconciles without a second action', exitCode === 70 && d5.actions.length === 1 &&
    d5.events.some((e) => e.kind === 'simulated_action_replay_detected'),
  { run_id: r5, note: `server exit code ${exitCode}`, screenshots: [s5a, s5b, s5c] });

  // 6. provider failure then recovery
  const r6 = await submit(page, 'Plan a campaign for Harbourlight Hotel with a S$20,000 budget', 'provider_error');
  await waitStatus(page, 'failed');
  await page.getByTestId('failure-panel').waitFor();
  const code = await page.getByTestId('error-code').innerText();
  const s6a = await shot(page, '12-provider-failure');
  await setRole(page, 'approver');
  await page.getByTestId('recover-run').click();
  await waitStatus(page, 'awaiting_approval');
  const d6 = await apiGet(`/api/runs/${r6}`);
  const s6b = await shot(page, '13-recovered-to-gate');
  record('provider failure is explicit; recover resumes to the gate', code === 'provider_error' && d6.actions.length === 0 &&
    d6.recover_count === 1, { run_id: r6, screenshots: [s6a, s6b] });

  // 7. grounded questions
  const r7 = await submit(page, 'Who must approve a campaign launch?');
  await waitStatus(page, 'completed');
  await page.getByTestId('answer-card').waitFor();
  const outcome7 = await page.getByTestId('answer-outcome').innerText();
  await page.getByTestId('citation').first().locator('button').click();
  const s7a = await shot(page, '14-grounded-answer');
  const r8 = await submit(page, 'How much of an image can be covered by text overlay?');
  await waitStatus(page, 'completed');
  const outcome8 = await page.getByTestId('answer-outcome').innerText();
  const s7b = await shot(page, '15-conflict');
  const r9 = await submit(page, 'How many monthly active users does the platform have?');
  await waitStatus(page, 'completed');
  const outcome9 = await page.getByTestId('answer-outcome').innerText();
  const s7c = await shot(page, '16-abstain');
  record('grounded answer / conflict / abstain shown with citations', outcome7 === 'answered' && outcome8 === 'conflict' &&
    outcome9 === 'abstained', { runs: [r7, r8, r9], screenshots: [s7a, s7b, s7c] });

  // 8. unsafe text renders as text
  const xss = 'Plan a campaign for Harbourlight Hotel <img src=x onerror="alert(1)"><script>alert(2)</script> =HYPERLINK("x") S$10,000';
  const r10 = await submit(page, xss);
  await waitStatus(page, 'awaiting_approval');
  const shown = await page.getByTestId('request-text').innerText();
  const injectedNodes = await page.evaluate(() => document.querySelectorAll('#root img, #root script').length);
  const csv = await (await fetch(`${BASE}/api/runs/${r10}/export.csv`)).text();
  const s8 = await shot(page, '17-unsafe-text-rendered-as-text');
  record('HTML/script shown as text, no dialog, CSV formula neutralised', shown.includes('<script>alert(2)</script>') &&
    injectedNodes === 0 && dialogs === 0 && !/\n[^,]*,[^,]*,[^,]*,=/.test(csv), { run_id: r10, screenshot: s8 });

  // 9. dashboard
  await page.getByTestId('nav-dashboard').click();
  await page.getByTestId('dashboard').waitFor();
  await page.waitForTimeout(500);
  const stats = await apiGet('/api/dashboard/stats');
  const uiPending = await page.getByTestId('stat-pending').innerText();
  const uiActions = await page.getByTestId('stat-actions').innerText();
  const s9 = await shot(page, '18-dashboard');
  record('dashboard shows stored aggregates', Number(uiPending) === stats.pending_approvals &&
    Number(uiActions) === stats.simulated_actions && stats.simulated_actions === 4 && stats.pending_approvals === 2, { note: `pending=${uiPending} actions=${uiActions}`, screenshot: s9 });
  const desktopOverflow = await overflow(page);

  // 10. mobile
  const m = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 });
  const mp = await m.newPage();
  mp.on('console', (msg) => { if (msg.type() === 'error') consoleLog.push({ text: `[mobile] ${msg.text()}`, duringServerDown: serverDownWindow }); });
  await mp.goto(`${BASE}/?run=${r10}`);
  await mp.getByTestId('proposal-card').waitFor();
  const mo1 = await overflow(mp);
  const sm1 = await shot(mp, '19-mobile-proposal');
  await mp.goto(`${BASE}/?run=${r5}`);
  await mp.getByTestId('action-receipt').waitFor();
  const mo2 = await overflow(mp);
  const sm2 = await shot(mp, '20-mobile-recovered');
  await mp.getByTestId('role-select').selectOption('approver');
  await mp.goto(`${BASE}/?run=${r10}`);
  await mp.getByTestId('approve-btn').tap();
  await mp.getByTestId('run-status').filter({ hasText: 'completed' }).waitFor({ timeout: 10000 });
  const mo3 = await overflow(mp);
  const sm3 = await shot(mp, '21-mobile-approved');
  record('mobile 390px: no horizontal overflow, approval works by tap', mo1 <= 0 && mo2 <= 0 && mo3 <= 0 && desktopOverflow <= 0,
    { note: `overflow px mobile=${mo1},${mo2},${mo3} desktop=${desktopOverflow}`, screenshots: [sm1, sm2, sm3] });

  await browser.close();
  await killServer('SIGTERM');

  const unexpected = consoleLog.filter((c) => !c.duringServerDown && !c.expectedNegativeStep);
  record('no console errors outside deliberate server-down / negative-test windows', unexpected.length === 0,
    { note: `${consoleLog.length} total, ${unexpected.length} unexpected`, console: consoleLog.slice(0, 30) });

  const passed = results.filter((r) => r.pass).length;
  const summary = { passed, total: results.length, browser: `chromium (playwright ${require('playwright/package.json').version})`,
    base: BASE, when: new Date().toISOString(), data_dir: 'temporary (deleted after run)' };
  fs.writeFileSync(path.join(OUT, 'results.json'), JSON.stringify({ summary, results }, null, 2));
  console.log(`\n${passed}/${results.length} E2E checks passed`);
  fs.rmSync(DATA, { recursive: true, force: true });
  process.exit(passed === results.length ? 0 : 1);
}

main().catch(async (e) => {
  console.error(e);
  try { await killServer(); } catch { /* ignore */ }
  fs.writeFileSync(path.join(OUT, 'results.json'), JSON.stringify({ error: String(e.stack || e), results }, null, 2));
  process.exit(2);
});
