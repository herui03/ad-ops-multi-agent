import React from 'react';
import {
  Brain, Search, Target, Palette,
  BarChart3, ShieldCheck, Swords
} from 'lucide-react';

const AGENT_META = {
  orchestrator: { label: 'Orchestrator',     icon: Brain },
  insight:      { label: 'Insight',           icon: Search },
  strategy:     { label: 'Strategy',          icon: Target },
  creative:     { label: 'Creative',          icon: Palette },
  analytics:    { label: 'Analytics',         icon: BarChart3 },
  compliance:   { label: 'Compliance',        icon: ShieldCheck },
  ci:           { label: 'Competitive Intel', icon: Swords },
};

// status → dot style
const DOT = {
  idle:         'bg-gray-300',
  planning:     'bg-blue-400 animate-pulse',
  running:      'bg-yellow-400 animate-pulse',
  synthesizing: 'bg-purple-400 animate-pulse',
  completed:    'bg-green-400',
  failed:       'bg-red-400',
};

function StatusLabel({ status, duration_ms }) {
  if (status === 'completed') {
    return (
      <span className="text-xs text-green-500 font-mono w-16 text-right">
        {duration_ms != null ? `${duration_ms}ms` : '✓'}
      </span>
    );
  }
  if (status === 'running' || status === 'planning' || status === 'synthesizing') {
    return <span className="text-xs text-yellow-500 w-16 text-right">{status}…</span>;
  }
  if (status === 'failed') {
    return <span className="text-xs text-red-400 w-16 text-right">failed</span>;
  }
  // idle
  return <span className="text-xs text-gray-300 w-16 text-right">idle</span>;
}

export default function AgentStatus({ statuses }) {
  return (
    <div className="p-4 border-b border-gray-100">
      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
        Agent Status
      </h3>
      <div className="space-y-2">
        {Object.entries(AGENT_META).map(([key, meta]) => {
          const Icon = meta.icon;
          const s = statuses?.[key] || {};
          const status = s.status || 'idle';
          const dotClass = DOT[status] ?? DOT.idle;

          return (
            <div
              key={key}
              className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-gray-50 transition-colors"
            >
              <Icon className="w-4 h-4 text-gray-400 shrink-0" />
              <span className="text-xs text-gray-700 flex-1 truncate">{meta.label}</span>
              <StatusLabel status={status} duration_ms={s.duration_ms} />
              {/* animated dot */}
              <span className={`w-2 h-2 rounded-full shrink-0 ${dotClass}`} />
            </div>
          );
        })}
      </div>
    </div>
  );
}