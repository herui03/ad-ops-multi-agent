import React, { useState, useRef, useEffect } from 'react';
import { Send, Loader2, User, Bot, Sparkles } from 'lucide-react';
import { sendMessage } from '../api';

const QUICK_ACTIONS = [
  'Create a CNY campaign plan for a Marina Bay hotel',
  'Analyze target audience for Singapore tourism sector',
  'Generate feed ad creatives for a luxury brand',
  'Weekly performance report for campaign #MBS-2026',
  'Our platform vs Instagram — comparison for client pitch',
];

export default function ChatPanel({ sessionId, onApprovalsReceived }) {
  const [messages, setMessages] = useState([{
    role: 'assistant',
    content: `Hello! I'm the Ad Ops Agent for the Singapore team\n\nI can help with:\n• Client insight & competitor analysis\n• Media strategy & planning\n• Ad creative generation\n• Performance analytics\n• Compliance review\n• Competitive intelligence\n\nWhat would you like to work on?`,
  }]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const endRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || isLoading) return;
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: text }]);
    setIsLoading(true);

    try {
      const result = await sendMessage(sessionId, text);
      console.log('🔍 trace:', result.agent_trace);

      const seen = new Set();
      const uniqueTrace = (result.agent_trace || []).filter(t => {
        if (seen.has(t.agent)) return false;
        seen.add(t.agent);
        return true;
      });

      setMessages(prev => [...prev, {
        role: 'assistant',
        content: result.message || 'Done.',
        trace: uniqueTrace,
        approvals: result.pending_approvals,
      }]);


      if (result.pending_approvals?.length > 0 && onApprovalsReceived) {
        onApprovalsReceived(result.pending_approvals);
      }

    } catch (err) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `Error: ${err.message}. Is the backend running?`,
      }]);
    } finally {
      setIsLoading(false);
      inputRef.current?.focus();
    }
  };

  return (
    <div className="flex flex-col h-full bg-gray-50">
      <div className="h-14 border-b border-gray-200 bg-white flex items-center px-4 gap-3 shrink-0">
        <div className="w-8 h-8 bg-green-100 rounded-lg flex items-center justify-center">
          <Sparkles className="w-4 h-4 text-green-600" />
        </div>
        <div>
          <h2 className="text-sm font-semibold text-gray-800">Ad Ops Agent</h2>
          <p className="text-xs text-gray-400">Singapore · Groq LPU · Multi-Agent</p>
        </div>
        <span className="ml-auto text-xs text-gray-400 font-mono">{sessionId}</span>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {messages.map((msg, i) => <MessageBubble key={i} message={msg} />)}
        {isLoading && (
          <div className="flex items-start gap-3">
            <div className="w-8 h-8 rounded-lg bg-green-100 flex items-center justify-center shrink-0">
              <Bot className="w-4 h-4 text-green-600" />
            </div>
            <div className="bg-white border border-gray-200 rounded-2xl rounded-tl-sm px-4 py-3">
              <div className="flex items-center gap-2 text-sm text-gray-500">
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Agents collaborating...</span>
              </div>
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      {messages.length <= 1 && (
        <div className="px-4 pb-2">
          <p className="text-xs text-gray-400 mb-2">Quick start:</p>
          <div className="flex flex-wrap gap-2">
            {QUICK_ACTIONS.map((a, i) => (
              <button
                key={i}
                onClick={() => { setInput(a); inputRef.current?.focus(); }}
                className="text-xs bg-white border border-gray-200 text-gray-600 px-3 py-1.5 rounded-full hover:bg-green-50 hover:border-green-300 hover:text-green-700 transition-colors"
              >
                {a}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="border-t border-gray-200 bg-white p-4 shrink-0">
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
            }}
            placeholder="Type your request... (Enter to send)"
            rows={1}
            className="flex-1 resize-none border border-gray-300 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent max-h-32"
            style={{ minHeight: '42px' }}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isLoading}
            className="w-10 h-10 bg-green-500 text-white rounded-xl flex items-center justify-center hover:bg-green-600 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors shrink-0"
          >
            {isLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          </button>
        </div>
      </div>
    </div>
  );
}

function formatInline(text) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    return part;
  });
}

function renderText(text) {
  return text.split('\n').map((line, i) => {
    if (/^[=\-*]{4,}$/.test(line.trim())) {
      return <hr key={i} className="my-2 border-gray-200" />;
    }
    if (line.startsWith('### ')) {
      return <p key={i} className="font-semibold text-sm mt-3 mb-1">{line.replace('### ', '')}</p>;
    }
    if (line.startsWith('## ')) {
      return <p key={i} className="font-bold text-base mt-3 mb-1">{line.replace('## ', '')}</p>;
    }
    if (line.startsWith('* ') || line.startsWith('- ') || line.startsWith('+ ')) {
      return (
        <div key={i} className="flex gap-1.5 ml-2">
          <span className="mt-0.5 text-gray-400 shrink-0">•</span>
          <span>{formatInline(line.slice(2))}</span>
        </div>
      );
    }
    if (/^\d+\.\s/.test(line)) {
      const match = line.match(/^(\d+)\.\s(.*)$/);
      return (
        <div key={i} className="flex gap-1.5 ml-2">
          <span className="shrink-0 text-gray-400">{match[1]}.</span>
          <span>{formatInline(match[2])}</span>
        </div>
      );
    }
    if (line.trim() === '') return <div key={i} className="h-1.5" />;
    return <p key={i}>{formatInline(line)}</p>;
  });
}

const AGENT_LABELS = {
          orchestrator: 'Orchestrator',
          insight: 'Insight',
          strategy: 'Strategy',
          creative: 'Creative',
          analytics: 'Analytics',
          compliance: 'Compliance',
          ci: 'Competitive Intel',
        };
function MessageBubble({ message }) {
  const isUser = message.role === 'user';
  return (
    <div className={`flex items-start gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${isUser ? 'bg-blue-100' : 'bg-green-100'}`}>
        {isUser
          ? <User className="w-4 h-4 text-blue-600" />
          : <Bot className="w-4 h-4 text-green-600" />}
      </div>
      <div
        className={`max-w-2xl min-w-0 rounded-2xl px-4 py-3 text-sm leading-relaxed ${
          isUser
            ? 'bg-green-500 text-white rounded-tr-sm'
            : 'bg-white border border-gray-200 text-gray-800 rounded-tl-sm'
        }`}
        style={{ overflowWrap: 'anywhere', wordBreak: 'break-word' }}
      >
        {isUser
          ? <div className="whitespace-pre-wrap">{message.content}</div>
          : <div className="space-y-0.5">{renderText(message.content)}</div>
        }
        {message.trace?.length > 0 && (
          <div className="mt-3 pt-2 border-t border-gray-100">
            <p className="text-xs text-gray-400 mb-1">Agent chain:</p>
            <div className="flex flex-wrap gap-1">
              {message.trace.map((t, i) => (
                <span
                  key={i}
                  className={`text-xs px-2 py-0.5 rounded-full ${
                    t.success !== false ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'
                  }`}
                >
                  {AGENT_LABELS[t.agent] || t.agent}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}