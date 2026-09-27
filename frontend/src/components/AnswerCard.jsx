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
      {answer.candidate_evidence?.length > 0 && (
        <div className="mt-2 rounded border border-dashed border-slate-300 p-2" data-testid="candidate-evidence">
          <p className="text-[11px] font-semibold text-slate-700">Candidate evidence: not an answer. Support was not established; read the source before relying on it.</p>
          <div className="mt-1 flex flex-col gap-1.5">
            {answer.candidate_evidence.map((c) => <Citation key={`cand-${c.chunk_id}`} chunkId={c.chunk_id} quote={c.quote} sha256={c.sha256} />)}
          </div>
        </div>
      )}
      {answer.ignored_question_text?.length > 0 && (
        <p className="mt-2 break-words text-[11px] text-amber-900" data-testid="ignored-question-text">
          Ignored instruction-like text in the question: {answer.ignored_question_text.join(' ')}
        </p>
      )}
      {answer.excluded_sources.length > 0 && (
        <div className="mt-2 rounded border border-amber-300 bg-amber-50 p-2 text-[11px] text-amber-900" data-testid="excluded-sources">
          {answer.excluded_sources.map((e) => <p key={e.chunk_id}>Excluded <Mono>{e.chunk_id}</Mono>: {e.reason}</p>)}
        </div>
      )}
    </Card>
  );
}
