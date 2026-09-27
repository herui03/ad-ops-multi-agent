import React from 'react';
import { Card, Mono, Pill } from './ui';
import Citation from './Citation';

export default function AnswerCard({ answer }) {
  return (
    <Card testid="answer-card" title="Grounded answer" right={<Pill value={answer.outcome} testid="answer-outcome" />}>
      <p className="break-words text-sm" data-testid="answer-text">{answer.answer_text}</p>
      <p className="mt-1 text-[11px] text-slate-500">Method: {answer.method}. Reason: <Mono>{answer.reason}</Mono></p>
      {answer.citations.length > 0 && (
        <div className="mt-2 flex flex-col gap-1.5">
          {answer.citations.map((c) => <Citation key={`${c.n}-${c.chunk_id}`} n={c.n} chunkId={c.chunk_id} quote={c.quote} sha256={c.sha256} />)}
        </div>
      )}
      {answer.excluded_sources.length > 0 && (
        <div className="mt-2 rounded border border-amber-300 bg-amber-50 p-2 text-[11px] text-amber-900" data-testid="excluded-sources">
          {answer.excluded_sources.map((e) => <p key={e.chunk_id}>Excluded <Mono>{e.chunk_id}</Mono>: {e.reason}</p>)}
        </div>
      )}
    </Card>
  );
}
