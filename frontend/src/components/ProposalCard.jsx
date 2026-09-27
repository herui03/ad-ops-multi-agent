import React, { useMemo, useRef, useState } from 'react';
import { newKey } from '../api';
import { Button, Card, fmtMoney, Mono, Pill } from './ui';
import Citation from './Citation';

export default function ProposalCard({ run, proposal, role, busy, onDecide, meta }) {
  const p = proposal.payload;
  const awaiting = run.status === 'awaiting_approval' && proposal.status === 'pending';
  const [comment, setComment] = useState('');
  const [budget, setBudget] = useState(String(p.amount));
  const [remove, setRemove] = useState([]);
  // One idempotency key per (proposal revision, decision). A double click re-sends the same key,
  // so the server replays the recorded decision instead of acting twice.
  const keys = useRef({});
  const keyFor = (decision) => {
    const k = `${proposal.proposal_id}:${proposal.revision}:${decision}`;
    if (!keys.current[k]) keys.current[k] = newKey(decision);
    return keys.current[k];
  };
  const base = { proposal_id: proposal.proposal_id, revision: proposal.revision, proposal_sha256: proposal.sha256, comment };
  const decide = (decision, extra = {}) => onDecide({ ...base, decision, idempotency_key: keyFor(decision), ...extra });

  const revisionChanges = useMemo(() => {
    const ch = {};
    const b = Number(budget);
    if (budget !== '' && !Number.isNaN(b) && b !== p.amount) ch.budget_total = b;
    if (remove.length) ch.remove_creative_ids = remove;
    return ch;
  }, [budget, remove, p.amount]);

  return (
    <Card testid="proposal-card" title={`Proposal · revision ${proposal.revision}`} right={<Pill value={proposal.status} testid="proposal-status" />}>
      <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
        <span>id <Mono>{proposal.proposal_id}</Mono></span>
        <span data-testid="proposal-sha">sha256 <Mono title={proposal.sha256}>{proposal.sha256.slice(0, 16)}…</Mono></span>
        <span className="rounded bg-slate-800 px-1.5 py-0.5 font-semibold text-white">{p.action_type}</span>
      </div>
      <p className="mb-2 rounded border border-slate-200 bg-slate-50 p-2 text-xs text-slate-700">{p.integration}</p>
      <div className="grid gap-3 md:grid-cols-2">
        <div className="min-w-0 text-sm">
          <p className="font-medium break-words">{p.campaign_name}</p>
          <p className="text-2xl font-semibold" data-testid="proposal-amount">{fmtMoney(p.amount, p.currency)}</p>
          {p.placements && (
            <ul className="mt-1 text-xs text-slate-700">
              {p.placements.map((pl) => <li key={pl.placement}>{pl.placement}: {pl.budget_pct}% · {fmtMoney(pl.amount, p.currency)}</li>)}
            </ul>
          )}
          {p.shifts && (
            <ul className="mt-1 text-xs text-slate-700">
              {p.shifts.map((s, i) => <li key={i}>Move {fmtMoney(s.amount, p.currency)} from {s.from_placement} to {s.to_placement}</li>)}
            </ul>
          )}
          {p.schedule && <p className="mt-1 text-xs text-slate-500">{p.schedule.start} → {p.schedule.end}</p>}
          {p.risk_flags?.length > 0 && <p className="mt-1 text-xs text-amber-800">{p.risk_flags.join('; ')}</p>}
        </div>
        <div className="min-w-0">
          {p.creatives?.length > 0 && (
            <ul className="flex flex-col gap-1.5">
              {p.creatives.map((c) => (
                <li key={c.creative_id} className="rounded border border-slate-200 p-2 text-xs" data-testid={`creative-${c.creative_id}`}>
                  <div className="flex items-center justify-between gap-2"><Mono>{c.creative_id}</Mono><span className="text-slate-500">{c.placement}</span></div>
                  <p className="font-medium break-words">{c.headline}</p>
                  <p className="break-words text-slate-600">{c.body}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {p.compliance?.findings?.length > 0 && (
        <div className="mt-3" data-testid="findings">
          <h4 className="text-xs font-semibold text-slate-700">Compliance findings ({p.compliance.blocking_count} blocking)</h4>
          <ul className="mt-1 flex flex-col gap-1">
            {p.compliance.findings.map((f) => (
              <li key={`${f.creative_id}-${f.rule_id}`} className="rounded border border-rose-200 bg-rose-50 p-2 text-xs">
                <span className="font-semibold">{f.severity.toUpperCase()}</span> {f.creative_id} · {f.rule_id} · <span className="break-words">{f.description}</span> <span className="text-slate-500">({f.source})</span>
                <div className="mt-1"><Citation chunkId={f.citation_chunk_id} /></div>
              </li>
            ))}
          </ul>
          <p className="mt-1 text-[11px] text-slate-500">{p.compliance.note}</p>
        </div>
      )}

      <div className={`mt-3 rounded border p-2 text-xs ${p.policy.approvable ? 'border-emerald-200 bg-emerald-50' : 'border-rose-300 bg-rose-50'}`} data-testid="policy-box">
        <p><span className="font-semibold">Gate policy:</span> {p.policy.rule}</p>
        {!p.policy.approvable && <p className="mt-1 font-semibold text-rose-800" data-testid="blockers">Blocked: {p.policy.blockers.join('; ')}</p>}
      </div>

      {awaiting ? (
        <div className="mt-3 flex flex-col gap-2" data-testid="decision-panel">
          <textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={2} placeholder="Comment (optional, stored with the decision)"
            maxLength={meta?.limits?.max_comment_chars || 500} className="w-full rounded border border-slate-300 p-2 text-sm" data-testid="decision-comment" />
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" disabled={busy} onClick={() => decide('approve')} testid="approve-btn"
              title={p.policy.approvable ? '' : 'Blocked by policy; the server will refuse'}>Approve revision {proposal.revision}</Button>
            <Button variant="danger" disabled={busy} onClick={() => decide('reject')} testid="reject-btn">Reject</Button>
          </div>
          <details className="rounded border border-slate-200 p-2 text-xs">
            <summary className="cursor-pointer font-medium text-slate-700">Request a revision</summary>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <label>Budget <input type="number" value={budget} onChange={(e) => setBudget(e.target.value)} data-testid="revise-budget"
                className="w-32 rounded border border-slate-300 px-1 py-0.5" /></label>
              {p.creatives?.map((c) => (
                <label key={c.creative_id} className="flex items-center gap-1">
                  <input type="checkbox" data-testid={`remove-${c.creative_id}`} checked={remove.includes(c.creative_id)}
                    onChange={(e) => setRemove((r) => e.target.checked ? [...r, c.creative_id] : r.filter((x) => x !== c.creative_id))} />
                  remove {c.creative_id}
                </label>
              ))}
              <Button disabled={busy || Object.keys(revisionChanges).length === 0} onClick={() => decide('revise', { changes: revisionChanges })} testid="revise-btn">
                Send revision request
              </Button>
            </div>
          </details>
          {role !== 'approver' && <p className="text-[11px] text-slate-500">You are acting as {role}. Decisions need the approver role; the server checks this.</p>}
        </div>
      ) : (
        <p className="mt-3 text-xs text-slate-600">No decision is pending on this revision.</p>
      )}

      {run.decisions?.length > 0 && (
        <div className="mt-3">
          <h4 className="text-xs font-semibold text-slate-700">Decision history</h4>
          <ul className="text-[11px]" data-testid="decision-history">
            {run.decisions.map((d) => (
              <li key={d.decision_id} className="break-words">
                <Mono>{d.decision_id}</Mono> {d.decision} rev {d.revision} by {d.actor} ({d.role}){d.comment ? `: "${d.comment}"` : ''}
                {d.changes ? ` changes=${JSON.stringify(d.changes)}` : ''}
              </li>
            ))}
          </ul>
        </div>
      )}
      {run.proposals.length > 1 && (
        <p className="mt-2 text-[11px] text-slate-500">
          Revisions: {run.proposals.map((x) => `r${x.revision} ${x.status}`).join(' · ')}
        </p>
      )}
    </Card>
  );
}
