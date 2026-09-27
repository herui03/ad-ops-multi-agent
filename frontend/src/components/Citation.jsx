import React, { useState } from 'react';
import { api } from '../api';
import { Mono } from './ui';

const KIND_LABEL = {
  'fictional-policy': 'fictional demo policy',
  'fictional-brand': 'fictional brand guidance',
  'unverified-summary': 'unverified summary, not legal advice',
  'unverified-vendor-note': 'untrusted vendor note',
};

export default function Citation({ chunkId, quote, sha256, n }) {
  const [src, setSrc] = useState(null);
  const [open, setOpen] = useState(false);
  const toggle = async () => {
    if (!src) {
      try { setSrc(await api.source(chunkId)); } catch (e) { setSrc({ error: e.message }); }
    }
    setOpen((o) => !o);
  };
  return (
    <div className="text-[11px]" data-testid="citation">
      {n ? <span className="font-semibold">[{n}] </span> : null}
      <button type="button" onClick={toggle} className="text-indigo-700 underline decoration-dotted">
        <Mono>{chunkId}</Mono>
      </button>
      {sha256 && <span className="text-slate-400"> sha256 <Mono>{sha256.slice(0, 12)}…</Mono></span>}
      {quote && <blockquote className="mt-0.5 break-words border-l-2 border-slate-300 pl-2 text-slate-700">{quote}</blockquote>}
      {open && src && (
        <div className="mt-1 rounded border border-slate-200 bg-slate-50 p-2">
          {src.error ? <span className="text-rose-700">{src.error}</span> : (
            <>
              <p className="font-medium">{src.title} v{src.version} · {KIND_LABEL[src.kind] || src.kind} · trust: {src.trust}</p>
              <p className="text-slate-500">{src.note}</p>
              <p className="mt-1 whitespace-pre-wrap break-words">{src.text}</p>
              <p className="mt-1 text-slate-500">sha256 <Mono>{src.sha256}</Mono></p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
