import React from 'react';

// All user- and source-provided text is rendered as React text nodes (escaped). There is no
// dangerouslySetInnerHTML anywhere in this UI.

const STATUS_STYLE = {
  queued: 'bg-slate-100 text-slate-700 border-slate-300',
  running: 'bg-sky-50 text-sky-800 border-sky-300',
  awaiting_approval: 'bg-amber-50 text-amber-900 border-amber-400',
  resuming: 'bg-sky-50 text-sky-800 border-sky-300',
  completed: 'bg-emerald-50 text-emerald-800 border-emerald-400',
  rejected: 'bg-rose-50 text-rose-800 border-rose-300',
  cancelled: 'bg-slate-100 text-slate-600 border-slate-300',
  failed: 'bg-rose-50 text-rose-800 border-rose-400',
  interrupted: 'bg-orange-50 text-orange-900 border-orange-400',
  pending: 'bg-slate-50 text-slate-500 border-slate-200',
  approved: 'bg-emerald-50 text-emerald-800 border-emerald-400',
  superseded: 'bg-slate-100 text-slate-500 border-slate-300',
  revision_requested: 'bg-violet-50 text-violet-800 border-violet-300',
  answered: 'bg-emerald-50 text-emerald-800 border-emerald-400',
  abstained: 'bg-slate-100 text-slate-700 border-slate-300',
  conflict: 'bg-amber-50 text-amber-900 border-amber-400',
};

export function Pill({ value, testid }) {
  const label = String(value || '').replaceAll('_', ' ');
  return (
    <span data-testid={testid} className={`inline-block whitespace-nowrap rounded border px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[value] || 'bg-slate-100 text-slate-700 border-slate-300'}`}>
      {label}
    </span>
  );
}

export function Card({ title, children, right, testid }) {
  return (
    <section data-testid={testid} className="rounded-lg border border-slate-200 bg-white p-3 sm:p-4">
      {(title || right) && (
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          {title && <h3 className="text-sm font-semibold text-slate-800">{title}</h3>}
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

export function Mono({ children, title }) {
  return <span title={title} className="mono break-all text-[11px] text-slate-600">{children}</span>;
}

export function Button({ children, onClick, disabled, variant = 'default', testid, title }) {
  const styles = {
    default: 'border-slate-300 bg-white text-slate-800 hover:bg-slate-50',
    primary: 'border-indigo-600 bg-indigo-600 text-white hover:bg-indigo-700',
    danger: 'border-rose-600 bg-white text-rose-700 hover:bg-rose-50',
    ghost: 'border-transparent bg-transparent text-slate-600 hover:bg-slate-100',
  };
  return (
    <button type="button" data-testid={testid} title={title} onClick={onClick} disabled={disabled}
      className={`rounded-md border px-3 py-1.5 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50 ${styles[variant]}`}>
      {children}
    </button>
  );
}

export function ErrorBox({ error, testid = 'error-box' }) {
  if (!error) return null;
  return (
    <div data-testid={testid} role="alert" className="rounded-md border border-rose-300 bg-rose-50 p-2 text-sm text-rose-800">
      <span className="font-semibold">{error.code || 'error'}</span>
      {error.status ? <span className="text-rose-600"> (HTTP {error.status})</span> : null}: {error.message}
    </div>
  );
}

export function fmtMoney(n, currency = 'SGD') {
  return `${Number(n).toLocaleString('en-SG', { maximumFractionDigits: 2 })} ${currency}`;
}

export function fmtTime(ts) {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}
