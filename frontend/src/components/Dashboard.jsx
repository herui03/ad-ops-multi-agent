import React, { useEffect, useState } from 'react';
import { api } from '../api';
import { Card, ErrorBox, fmtMoney } from './ui';

export default function Dashboard() {
  const [s, setS] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    const load = () => api.stats().then(setS).catch(setError);
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, []);
  if (error) return <ErrorBox error={error} />;
  if (!s) return <p className="text-sm text-slate-500">Loading…</p>;
  const tiles = [
    ['Runs (this instance)', s.runs_total, 'stat-runs'],
    ['Pending approvals', s.pending_approvals, 'stat-pending'],
    ['Simulated actions', s.simulated_actions, 'stat-actions'],
    ['Simulated amount', fmtMoney(s.simulated_amount_committed), 'stat-amount'],
  ];
  return (
    <div className="flex flex-col gap-3" data-testid="dashboard">
      <p className="rounded border border-slate-200 bg-white p-2 text-xs text-slate-600">{s.note}</p>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {tiles.map(([label, value, id]) => (
          <div key={id} className="rounded-lg border border-slate-200 bg-white p-3">
            <p className="text-xs text-slate-500">{label}</p>
            <p className="text-xl font-semibold" data-testid={id}>{value}</p>
          </div>
        ))}
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <Card title="Runs by status">
          <table className="w-full text-sm"><tbody>
            {Object.entries(s.runs_by_status).map(([k, v]) => <tr key={k}><td className="py-0.5">{k}</td><td className="text-right font-medium">{v}</td></tr>)}
          </tbody></table>
        </Card>
        <Card title="Decisions by type">
          <table className="w-full text-sm"><tbody>
            {Object.entries(s.decisions_by_type).map(([k, v]) => <tr key={k}><td className="py-0.5">{k}</td><td className="text-right font-medium">{v}</td></tr>)}
          </tbody></table>
        </Card>
      </div>
    </div>
  );
}
