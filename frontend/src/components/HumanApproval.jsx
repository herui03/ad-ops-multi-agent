import React, { useState } from 'react';
import { AlertTriangle, Check, X, MessageSquare } from 'lucide-react';
import { submitApproval } from '../api';

export default function HumanApproval({ approvals, onResolved }) {
  return (
    <div className="p-4">
      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3 flex items-center gap-1">
        <AlertTriangle className="w-3.5 h-3.5 text-amber-500" />
        Needs Approval ({approvals.length})
      </h3>
      <div className="space-y-3">
        {approvals.map(a => (
          <ApprovalCard key={a.approval_id} approval={a} onResolved={onResolved} />
        ))}
      </div>
    </div>
  );
}

function ApprovalCard({ approval, onResolved }) {
  const [feedback, setFeedback] = useState('');
  const [showFeedback, setShowFeedback] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleDecision = async (decision) => {
    setIsSubmitting(true);
    try {
      await submitApproval(approval.approval_id, decision, feedback);
      onResolved(approval.approval_id);
    } catch (err) {
      console.error(err);
    } finally {
      setIsSubmitting(false);
    }
  };

  const colors = {
    budget: 'border-amber-200 bg-amber-50',
    compliance: 'border-red-200 bg-red-50',
  };

  return (
    <div className={`rounded-xl border p-3 ${colors[approval.approval_type] || 'border-gray-200 bg-gray-50'}`}>
      <p className="text-xs font-semibold text-gray-800 mb-1">{approval.title}</p>
      <p className="text-xs text-gray-600 mb-3">{approval.description}</p>
      {showFeedback && (
        <textarea
          value={feedback}
          onChange={e => setFeedback(e.target.value)}
          placeholder="Optional feedback..."
          rows={2}
          className="w-full text-xs border border-gray-200 rounded-lg px-2 py-1.5 mb-2 resize-none focus:outline-none focus:ring-1 focus:ring-green-500"
        />
      )}
      <div className="flex items-center gap-2">
        <button
          onClick={() => handleDecision('approved')}
          disabled={isSubmitting}
          className="flex items-center gap-1 text-xs bg-green-500 text-white px-3 py-1.5 rounded-lg hover:bg-green-600 disabled:opacity-50"
        >
          <Check className="w-3 h-3" /> Approve
        </button>
        <button
          onClick={() => handleDecision('rejected')}
          disabled={isSubmitting}
          className="flex items-center gap-1 text-xs bg-red-500 text-white px-3 py-1.5 rounded-lg hover:bg-red-600 disabled:opacity-50"
        >
          <X className="w-3 h-3" /> Reject
        </button>
        <button
          onClick={() => setShowFeedback(!showFeedback)}
          className="flex items-center gap-1 text-xs text-gray-500 px-2 py-1.5 rounded-lg hover:bg-white"
        >
          <MessageSquare className="w-3 h-3" /> Feedback
        </button>
      </div>
    </div>
  );
}
