import React, { useCallback, useEffect, useState } from 'react';
import { api, ROLES } from './api';
import { Button, ErrorBox, Pill, Mono } from './components/ui';
import RunDetail from './components/RunDetail';
import Composer from './components/Composer';
import Dashboard from './components/Dashboard';
import Sources from './components/Sources';

function readRole() {
  try { return localStorage.getItem('demo-role') || 'requester'; } catch { return 'requester'; }
}

export default function App() {
  const [meta, setMeta] = useState(null);
  const [metaError, setMetaError] = useState(null);
  const [role, setRole] = useState(readRole);
  const [view, setView] = useState('runs');
  const [runs, setRuns] = useState([]);
  const [selected, setSelected] = useState(() => new URLSearchParams(window.location.search).get('run'));

  useEffect(() => { api.meta().then(setMeta).catch(setMetaError); }, []);
  useEffect(() => { try { localStorage.setItem('demo-role', role); } catch { /* storage unavailable */ } }, [role]);

  const refreshRuns = useCallback(() => api.runs().then((d) => setRuns(d.runs)).catch(() => {}), []);
  useEffect(() => {
    refreshRuns();
    const t = setInterval(refreshRuns, 3000);
    return () => clearInterval(t);
  }, [refreshRuns]);

  const select = (id) => {
    setSelected(id);
    setView('runs');
    const url = new URL(window.location.href);
    url.searchParams.set('run', id);
    window.history.replaceState(null, '', url);
  };

  const live = meta?.provider_mode === 'live';
  return (
    <div className="min-h-screen text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
          <div className="min-w-0">
            <h1 className="text-base font-semibold">Ad Ops Approval Gate</h1>
            <p className="text-xs text-slate-500">Simulated advertising-operations workflow · portfolio prototype · fictional data</p>
          </div>
          <span data-testid="mode-badge" title={meta?.provider_label}
            className={`rounded border px-2 py-0.5 text-xs font-semibold ${live ? 'border-violet-400 bg-violet-50 text-violet-800' : 'border-amber-400 bg-amber-50 text-amber-900'}`}>
            {meta ? (live ? 'LIVE provider' : 'DEMO · deterministic provider · offline') : '…'}
          </span>
          <nav className="flex gap-1" aria-label="views">
            {['runs', 'dashboard', 'sources'].map((v) => (
              <Button key={v} variant={view === v ? 'primary' : 'ghost'} onClick={() => setView(v)} testid={`nav-${v}`}>
                {v[0].toUpperCase() + v.slice(1)}
              </Button>
            ))}
          </nav>
          <label className="ml-auto flex items-center gap-2 text-xs text-slate-600">
            Acting as
            <select data-testid="role-select" value={role} onChange={(e) => setRole(e.target.value)}
              className="rounded border border-slate-300 bg-white px-2 py-1 text-sm">
              {Object.entries(ROLES).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </select>
          </label>
        </div>
        <div className="border-t border-amber-200 bg-amber-50 px-4 py-1.5 text-center text-[11px] text-amber-900">
          Demo roles are a dropdown, not a login. The server enforces them, but it cannot tell who you are.
          Approved actions write to a simulated ledger only: no ad platform is called and no money is spent.
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-4">
        {metaError && <ErrorBox error={metaError} />}
        {view === 'dashboard' && <Dashboard />}
        {view === 'sources' && <Sources />}
        {view === 'runs' && (
          <div className="grid gap-4 lg:grid-cols-[340px_minmax(0,1fr)]">
            <div className="flex min-w-0 flex-col gap-4">
              <Composer role={role} meta={meta} onCreated={(id) => { refreshRuns(); select(id); }} />
              <section className="rounded-lg border border-slate-200 bg-white p-3">
                <h2 className="mb-2 text-sm font-semibold">Runs <span className="font-normal text-slate-500">(persisted)</span></h2>
                {runs.length === 0 && <p className="text-sm text-slate-500">No runs yet.</p>}
                <ul className="flex max-h-[420px] flex-col gap-1 overflow-y-auto" data-testid="run-list">
                  {runs.map((r) => (
                    <li key={r.run_id}>
                      <button type="button" onClick={() => select(r.run_id)} data-testid={`run-item-${r.run_id}`}
                        className={`w-full rounded-md border px-2 py-1.5 text-left ${selected === r.run_id ? 'border-indigo-400 bg-indigo-50' : 'border-transparent hover:bg-slate-50'}`}>
                        <div className="flex items-center justify-between gap-2">
                          <Mono>{r.run_id}</Mono>
                          <Pill value={r.status} />
                        </div>
                        <p className="mt-0.5 line-clamp-2 break-words text-xs text-slate-700">{r.request_text}</p>
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            </div>
            {/* On small screens the selected run (and its approval card) comes first. */}
            <div className="order-first min-w-0 lg:order-none">
              {selected ? <RunDetail key={selected} runId={selected} role={role} meta={meta} onChange={refreshRuns} />
                : <p className="rounded-lg border border-dashed border-slate-300 p-6 text-sm text-slate-500">Create a run or pick one from the list.</p>}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
