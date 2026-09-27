import React, { useCallback, useEffect, useRef, useState } from 'react';
import { api, newKey, runSocketUrl } from '../api';
import { Button, Card, ErrorBox, fmtMoney, fmtTime, Mono, Pill } from './ui';
import ProposalCard from './ProposalCard';
import AnswerCard from './AnswerCard';

const TERMINAL = new Set(['completed', 'rejected', 'cancelled']);

export default function RunDetail({ runId, role, meta, onChange }) {
  const [run, setRun] = useState(null);
  const [error, setError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [socket, setSocket] = useState('connecting');
  const [busy, setBusy] = useState(false);
  const cancelKey = useRef(newKey('cancel'));

  const load = useCallback(async () => {
    try {
      const d = await api.run(runId);
      setRun(d);
      setError(null);
    } catch (e) {
      setError(e);
    }
  }, [runId]);

  // Live updates: a read-only WebSocket streams persisted events; every event triggers a refetch of
  // the durable state. If the socket drops, we reconnect with backoff and keep polling meanwhile.
  useEffect(() => {
    let ws; let stopped = false; let retry = 0; let timer;
    const connect = () => {
      setSocket(retry ? 'reconnecting' : 'connecting');
      ws = new WebSocket(runSocketUrl(runId));
      ws.onopen = () => { retry = 0; setSocket('live'); };
      ws.onmessage = (e) => {
        const msg = JSON.parse(e.data);
        if (msg.type === 'snapshot') setRun(msg.run);
        if (msg.type === 'events') { load(); onChange?.(); }
      };
      ws.onclose = () => {
        if (stopped) return;
        setSocket('reconnecting');
        retry += 1;
        timer = setTimeout(connect, Math.min(8000, 500 * 2 ** retry));
      };
    };
    connect();
    const poll = setInterval(load, 2500);
    return () => { stopped = true; clearTimeout(timer); clearInterval(poll); ws && ws.close(); };
  }, [runId, load, onChange]);

  const act = async (fn) => {
    setBusy(true);
    setActionError(null);
    try {
      await fn();
      await load();
      onChange?.();
    } catch (e) {
      setActionError(e);
      await load();
    } finally {
      setBusy(false);
    }
  };

  if (error && !run) return <ErrorBox error={error} />;
  if (!run) return <p className="text-sm text-slate-500">Loading run…</p>;

  const proposal = run.proposals?.[run.proposals.length - 1];
  const canCancel = !TERMINAL.has(run.status) && run.status !== 'resuming';
  const canRecover = run.status === 'interrupted' || (run.status === 'failed' && run.retryable);

  return (
    <div className="flex flex-col gap-3" data-testid="run-detail">
      <Card testid="run-header">
        <div className="flex flex-wrap items-center gap-2">
          <Pill value={run.status} testid="run-status" />
          <span className={`rounded border px-1.5 py-0.5 text-[11px] ${run.provider_mode === 'live' ? 'border-violet-300 text-violet-800' : 'border-amber-300 text-amber-900'}`}>
            {run.provider_mode === 'live' ? 'live provider' : 'demo provider'}
          </span>
          <span className="text-[11px] text-slate-500">socket: <span data-testid="socket-state">{socket}</span></span>
          <div className="ml-auto flex flex-wrap gap-2">
            {canCancel && <Button variant="danger" disabled={busy} testid="cancel-run"
              onClick={() => act(() => api.cancel(role, runId, cancelKey.current))}>Cancel run</Button>}
            <a className="rounded-md border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50" href={`/api/runs/${runId}/export.json`} data-testid="export-json">Export JSON</a>
            <a className="rounded-md border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50" href={`/api/runs/${runId}/export.csv`} data-testid="export-csv">Export CSV</a>
          </div>
        </div>
        <p className="mt-2 whitespace-pre-wrap break-words text-sm text-slate-800" data-testid="request-text">{run.request_text}</p>
        <dl className="mt-2 grid grid-cols-1 gap-x-4 gap-y-0.5 text-[11px] sm:grid-cols-2">
          <div><dt className="inline text-slate-500">run_id </dt><dd className="inline"><Mono>{run.run_id}</Mono></dd></div>
          <div><dt className="inline text-slate-500">thread_id </dt><dd className="inline"><Mono>{run.checkpoint?.thread_id}</Mono></dd></div>
          <div><dt className="inline text-slate-500">requester </dt><dd className="inline"><Mono>{run.requester}</Mono></dd></div>
          <div><dt className="inline text-slate-500">checkpoint next </dt><dd className="inline" data-testid="checkpoint-next"><Mono>{(run.checkpoint?.next_nodes || []).join(', ') || '(end)'}</Mono></dd></div>
          <div><dt className="inline text-slate-500">recoveries </dt><dd className="inline"><Mono>{run.recover_count}</Mono></dd></div>
          <div><dt className="inline text-slate-500">workflow </dt><dd className="inline"><Mono>{run.route || '…'}{run.workflow_type ? ` / ${run.workflow_type}` : ''}</Mono></dd></div>
        </dl>
        <div className="mt-2"><ErrorBox error={actionError} testid="action-error" /></div>
      </Card>

      {(run.status === 'failed' || run.status === 'interrupted') && (
        <Card testid="failure-panel" title={run.status === 'failed' ? 'Run failed' : 'Run interrupted'}>
          <p className="text-sm text-rose-800"><span className="font-semibold" data-testid="error-code">{run.error_code}</span>: <span className="break-words">{run.error_message}</span></p>
          <p className="mt-1 text-xs text-slate-600">
            {canRecover ? 'Recover resumes from the last LangGraph checkpoint. Completed steps are not re-run.' : 'This run cannot be recovered (non-retryable or recovery limit reached).'}
          </p>
          {canRecover && <div className="mt-2"><Button variant="primary" disabled={busy} testid="recover-run"
            onClick={() => act(() => api.recover(role, runId))}>Recover from checkpoint</Button></div>}
        </Card>
      )}

      {run.steps?.length > 0 && (
        <Card title="Plan (validated DAG) and agent steps" testid="steps">
          <ol className="flex flex-col gap-1">
            {run.steps.map((s) => (
              <li key={s.step_id} className="flex flex-wrap items-center gap-2 text-sm" data-testid={`step-${s.agent}`}>
                <Mono>{s.step_id}</Mono>
                <span className="w-24 font-medium">{s.agent}</span>
                <Pill value={s.status} />
                <span className="text-[11px] text-slate-500">attempts {s.attempts}</span>
                {s.error_code && <span className="break-words text-[11px] text-rose-700">{s.error_code}: {s.error_message}</span>}
              </li>
            ))}
          </ol>
        </Card>
      )}

      {run.result?.kind === 'answer' && <AnswerCard answer={run.result.answer} />}

      {proposal && (
        <ProposalCard key={proposal.proposal_id} run={run} proposal={proposal} role={role} busy={busy} meta={meta}
          onDecide={(body) => act(() => api.decide(role, runId, body))} />
      )}

      {run.actions?.length > 0 && (
        <Card title="Simulated action (ledger)" testid="action-receipt">
          {run.actions.map((a) => (
            <div key={a.action_id} className="text-sm">
              <span className="mr-2 rounded bg-slate-800 px-1.5 py-0.5 text-[11px] font-semibold text-white">SIMULATED</span>
              {a.action_type} · {fmtMoney(a.amount, a.currency)} · <Mono>{a.action_id}</Mono>
              <p className="mt-1 text-xs text-slate-600">Approved proposal <Mono>{a.proposal_id}</Mono> rev {a.revision}. {a.payload?.integration}</p>
            </div>
          ))}
          {run.result?.replay_detected && <p className="mt-1 text-xs text-amber-800" data-testid="replay-note">Replay detected during recovery: the existing ledger row was reused, not re-executed.</p>}
        </Card>
      )}

      {run.result && run.result.kind !== 'answer' && (
        <Card title="Outcome" testid="outcome">
          <p className="break-words text-sm">{run.result.summary || run.result.note}</p>
          {run.result.kind === 'deliverable' && (
            <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-50 p-2 text-[11px]">{JSON.stringify(run.result.outputs, null, 2)}</pre>
          )}
        </Card>
      )}

      <Card title={`Event history (${run.events?.length || 0}, persisted)`} testid="timeline">
        <ol className="max-h-72 overflow-y-auto text-[11px]">
          {(run.events || []).map((e) => (
            <li key={e.seq} className="flex gap-2 border-b border-slate-100 py-0.5">
              <span className="mono w-8 shrink-0 text-slate-400">{e.seq}</span>
              <span className="w-16 shrink-0 text-slate-500">{fmtTime(e.ts)}</span>
              <span className="min-w-0 break-words"><span className="font-medium">{e.kind}</span> <span className="text-slate-500">{summarize(e.data)}</span></span>
            </li>
          ))}
        </ol>
      </Card>
    </div>
  );
}

function summarize(data) {
  if (!data) return '';
  const keys = ['agent', 'role', 'attempt', 'outcome', 'code', 'decision', 'revision', 'action', 'to', 'message'];
  return keys.filter((k) => data[k] !== undefined && data[k] !== null && data[k] !== '').map((k) => `${k}=${data[k]}`).join(' ');
}
