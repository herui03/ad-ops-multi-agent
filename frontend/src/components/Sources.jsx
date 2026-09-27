import React, { useEffect, useState } from 'react';
import { api } from '../api';
import { Card, ErrorBox, Mono } from './ui';

export default function Sources() {
  const [docs, setDocs] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { api.sources().then((d) => setDocs(d.documents)).catch(setError); }, []);
  if (error) return <ErrorBox error={error} />;
  if (!docs) return <p className="text-sm text-slate-500">Loading…</p>;
  return (
    <div className="flex flex-col gap-3" data-testid="sources">
      <p className="rounded border border-amber-300 bg-amber-50 p-2 text-xs text-amber-900">
        The corpus is small and hand-written. Policies and brands are fictional; regulation and platform notes are
        unverified paraphrases. Citations prove where a sentence came from, not that it is current law or legal approval.
      </p>
      {docs.map((d) => (
        <Card key={d.doc_id} title={`${d.title} v${d.version}`} right={<span className="text-[11px] text-slate-500">{d.chunks} chunks</span>}>
          <p className="text-xs"><Mono>{d.doc_id}</Mono> · kind <b>{d.kind}</b> · trust <b>{d.trust}</b></p>
          <p className="mt-1 text-xs text-slate-600">{d.note}</p>
        </Card>
      ))}
    </div>
  );
}
