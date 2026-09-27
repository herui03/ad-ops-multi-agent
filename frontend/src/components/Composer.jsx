import React, { useState } from 'react';
import { api } from '../api';
import { Button, ErrorBox } from './ui';

const EXAMPLES = [
  { label: 'Campaign (approvable)', text: 'Plan a year-end campaign for Harbourlight Hotel with a S$80,000 budget' },
  { label: 'Campaign with a blocked claim', text: 'Launch a campaign saying Harbourlight Hotel is the best harbour view, S$40,000' },
  { label: 'Performance review', text: 'Review campaign performance and shift budget from weak placements' },
  { label: 'Policy question', text: 'Who must approve a campaign launch?' },
  { label: 'Conflicting sources', text: 'How much of an image can be covered by text overlay?' },
  { label: 'Unanswerable question', text: 'How many monthly active users does the platform have?' },
];

export default function Composer({ role, meta, onCreated }) {
  const [text, setText] = useState(EXAMPLES[0].text);
  const [fault, setFault] = useState('');
  const [faultAgent, setFaultAgent] = useState('strategy');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const max = meta?.limits?.max_request_chars || 2000;

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const demoFault = fault ? { kind: fault, agent: faultAgent, fail_attempts: 2 } : undefined;
      const res = await api.createRun(role, text, demoFault);
      onCreated(res.run.run_id);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-3" data-testid="composer">
      <h2 className="mb-2 text-sm font-semibold">New request</h2>
      <div className="mb-2 flex flex-wrap gap-1">
        {EXAMPLES.map((ex) => (
          <button key={ex.label} type="button" onClick={() => setText(ex.text)}
            className="rounded border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-100">
            {ex.label}
          </button>
        ))}
      </div>
      <textarea data-testid="request-input" value={text} onChange={(e) => setText(e.target.value)} rows={3}
        className="w-full rounded-md border border-slate-300 p-2 text-sm" aria-label="request text" />
      <div className="mt-1 flex justify-between text-[11px] text-slate-500">
        <span>Plain text; shown back as text, never as HTML.</span>
        <span className={text.length > max ? 'text-rose-600' : ''}>{text.length}/{max}</span>
      </div>
      {meta?.demo_faults_enabled && (
        <details className="mt-2 rounded border border-dashed border-slate-300 p-2 text-xs">
          <summary className="cursor-pointer text-slate-600">Demo fault injection (for failure/recovery demos)</summary>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <select data-testid="fault-kind" value={fault} onChange={(e) => setFault(e.target.value)} className="rounded border border-slate-300 px-1 py-0.5">
              <option value="">none</option>
              <option value="provider_error">provider error</option>
              <option value="timeout">timeout</option>
              <option value="malformed_json">malformed JSON</option>
              <option value="wrong_schema">wrong schema</option>
            </select>
            on
            <select value={faultAgent} onChange={(e) => setFaultAgent(e.target.value)} className="rounded border border-slate-300 px-1 py-0.5">
              {['planner', 'insight', 'strategy', 'creative', 'compliance', 'analytics'].map((a) => <option key={a}>{a}</option>)}
            </select>
            <span className="text-slate-500">fails the first 2 attempts (the retry budget), so the step fails; Recover then succeeds.</span>
          </div>
        </details>
      )}
      <div className="mt-2 flex items-center gap-2">
        <Button variant="primary" onClick={submit} disabled={busy || !text.trim()} testid="submit-request">
          {busy ? 'Submitting…' : 'Submit request'}
        </Button>
        {role !== 'requester' && <span className="text-xs text-slate-500">Only the requester role may submit; the server will refuse other roles.</span>}
      </div>
      <div className="mt-2"><ErrorBox error={error} testid="composer-error" /></div>
    </section>
  );
}
