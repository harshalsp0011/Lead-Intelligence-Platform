/**
 * Chat Page
 *
 * Conversational interface to the agent backend.
 * Uses a background-task + polling approach:
 *   1. POST /chat  → run_id returned immediately
 *   2. Poll /pipeline/run/{run_id} every 2 s → show live progress steps
 *   3. Poll /chat/result/{run_id}  every 2 s → show final reply when done
 *
 * Examples:
 *   "find 10 healthcare companies in Buffalo NY"
 *   "show me all high-tier leads"
 *   "which companies have we already emailed?"
 *   "did anyone reply to our emails?"
 *   "run the full pipeline for manufacturing in Buffalo"
 */

import React, { useState, useRef, useEffect, useCallback } from 'react';
import { startChat, fetchChatResult, fetchRunStatus } from '../services/api';

// ---------------------------------------------------------------------------
// Quick-prompt suggestions shown before first message
// ---------------------------------------------------------------------------
const SUGGESTIONS = [
  'Find 10 healthcare companies in Buffalo NY',
  'Show me all high-tier leads',
  'Which companies have we already emailed?',
  'Did anyone reply to our emails?',
  'Run the full pipeline for healthcare in Buffalo NY',
];

// ---------------------------------------------------------------------------
// Inline result renderers
// ---------------------------------------------------------------------------

function CompanyCard({ company }) {
  return (
    <div className="bg-white border border-slate-200 rounded-lg p-3 text-xs">
      <p className="font-semibold text-slate-800 truncate">{company.name}</p>
      <p className="text-slate-500 mt-0.5">
        {company.industry} · {company.city}{company.state ? `, ${company.state}` : ''}
      </p>
      {company.website && (
        <a
          href={company.website}
          target="_blank"
          rel="noreferrer"
          className="text-blue-500 hover:underline mt-0.5 block truncate"
        >
          {company.website}
        </a>
      )}
      <div className="flex items-center gap-2 mt-1.5">
        <span className="bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded text-xs">
          {company.source || 'scraped'}
        </span>
        <span className={`px-1.5 py-0.5 rounded text-xs ${
          company.status === 'approved' ? 'bg-green-100 text-green-700' : 'bg-slate-100 text-slate-600'
        }`}>
          {company.status}
        </span>
      </div>
    </div>
  );
}

function LeadCard({ lead }) {
  const tierColor = {
    high: 'bg-green-100 text-green-700',
    medium: 'bg-yellow-100 text-yellow-700',
    low: 'bg-slate-100 text-slate-600',
    unscored: 'bg-slate-100 text-slate-400',
  }[lead.tier] || 'bg-slate-100 text-slate-600';

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-3 text-xs">
      <div className="flex items-start justify-between gap-2">
        <p className="font-semibold text-slate-800 truncate">{lead.name}</p>
        <span className={`px-1.5 py-0.5 rounded flex-shrink-0 ${tierColor}`}>
          {lead.tier}
        </span>
      </div>
      <p className="text-slate-500 mt-0.5">{lead.industry} · {lead.city}{lead.state ? `, ${lead.state}` : ''}</p>
      <div className="flex items-center gap-3 mt-1.5">
        <span className="text-slate-700 font-medium">Score: {lead.score.toFixed(1)}</span>
        {lead.approved && <span className="text-green-600">✓ Approved</span>}
      </div>
    </div>
  );
}

function ReplyCard({ reply }) {
  const sentimentColor = {
    positive: 'bg-green-100 text-green-700',
    neutral: 'bg-blue-100 text-blue-700',
    negative: 'bg-red-100 text-red-700',
    unknown: 'bg-slate-100 text-slate-600',
  }[reply.reply_sentiment] || 'bg-slate-100 text-slate-600';

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-3 text-xs">
      <div className="flex items-start justify-between gap-2">
        <p className="font-semibold text-slate-800">{reply.name}</p>
        <span className={`px-1.5 py-0.5 rounded flex-shrink-0 ${sentimentColor}`}>
          {reply.reply_sentiment}
        </span>
      </div>
      <p className="text-slate-500 mt-0.5">{reply.industry}</p>
      {reply.reply_snippet && (
        <p className="text-slate-700 mt-1.5 italic">"{reply.reply_snippet}"</p>
      )}
      <p className="text-slate-400 mt-1">{reply.replied_at ? new Date(reply.replied_at).toLocaleDateString() : ''}</p>
    </div>
  );
}

function DataSection({ data }) {
  if (!data) return null;

  const companies = data.companies || [];
  const leads = data.leads || [];
  const replies = data.replies || [];
  const history = data.outreach_history || [];
  const summary = data.pipeline_summary;

  const hasData = companies.length || leads.length || replies.length || history.length || summary;
  if (!hasData) return null;

  return (
    <div className="mt-3 space-y-3">
      {summary && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-xs">
          <p className="font-semibold text-blue-800 mb-1.5">Pipeline Run Summary</p>
          <div className="grid grid-cols-2 gap-1 text-blue-700">
            <span>Companies found:</span><span className="font-medium">{summary.companies_found}</span>
            <span>Scored high:</span><span className="font-medium">{summary.scored_high}</span>
            <span>Scored medium:</span><span className="font-medium">{summary.scored_medium}</span>
            <span>Contacts found:</span><span className="font-medium">{summary.contacts_found}</span>
            <span>Drafts created:</span><span className="font-medium">{summary.drafts_created}</span>
          </div>
        </div>
      )}

      {companies.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
            Companies Found ({companies.length})
          </p>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {companies.map((c) => <CompanyCard key={c.company_id} company={c} />)}
          </div>
        </div>
      )}

      {leads.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
            Leads ({leads.length})
          </p>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {leads.slice(0, 10).map((l) => <LeadCard key={l.company_id} lead={l} />)}
            {leads.length > 10 && (
              <p className="text-xs text-slate-400 col-span-2">
                + {leads.length - 10} more — go to Leads page to see all
              </p>
            )}
          </div>
        </div>
      )}

      {replies.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
            Replies ({replies.length})
          </p>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {replies.map((r) => <ReplyCard key={r.company_id} reply={r} />)}
          </div>
        </div>
      )}

      {history.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
            Outreach History ({history.length})
          </p>
          <div className="space-y-1">
            {history.slice(0, 8).map((h) => (
              <div key={h.company_id} className="flex items-center justify-between bg-white border border-slate-200 rounded px-3 py-2 text-xs">
                <span className="font-medium text-slate-700">{h.name}</span>
                <span className="text-slate-400">
                  {h.emailed_at ? new Date(h.emailed_at).toLocaleDateString() : '—'}
                  {h.follow_up_number > 0 && ` · Follow-up #${h.follow_up_number}`}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Message bubble
// ---------------------------------------------------------------------------
function Message({ msg }) {
  const isUser = msg.role === 'user';
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}>
      {!isUser && (
        <div className="w-7 h-7 rounded-full bg-blue-600 flex items-center justify-center text-white text-xs font-bold mr-2 flex-shrink-0 mt-0.5">
          A
        </div>
      )}
      <div className={`max-w-[80%] ${isUser ? 'items-end' : 'items-start'} flex flex-col`}>
        <div className={`px-4 py-2.5 rounded-2xl text-sm leading-relaxed ${
          isUser
            ? 'bg-blue-600 text-white rounded-tr-sm'
            : 'bg-white border border-slate-200 text-slate-800 rounded-tl-sm shadow-sm'
        }`}>
          {msg.content}
        </div>
        {msg.data && <DataSection data={msg.data} />}
        {msg.runId && (
          <p className="text-xs text-slate-400 mt-1">Run ID: {msg.runId.slice(0, 8)}…</p>
        )}
      </div>
      {isUser && (
        <div className="w-7 h-7 rounded-full bg-slate-300 flex items-center justify-center text-slate-600 text-xs font-bold ml-2 flex-shrink-0 mt-0.5">
          U
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Live progress indicator — shows step-by-step agent activity
// ---------------------------------------------------------------------------
function ProgressIndicator({ steps }) {
  return (
    <div className="flex items-start mb-4">
      <div className="w-7 h-7 rounded-full bg-blue-600 flex items-center justify-center text-white text-xs font-bold mr-2 flex-shrink-0">
        A
      </div>
      <div className="bg-white border border-slate-200 rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm max-w-sm">
        {/* Bounce dots */}
        <div className="flex gap-1.5 items-center mb-2">
          <div className="w-2 h-2 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
          <div className="w-2 h-2 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
          <div className="w-2 h-2 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
          <span className="text-xs text-slate-400 ml-1">Agent is working…</span>
        </div>
        {/* Progress steps */}
        {steps.length > 0 && (
          <div className="space-y-1 border-t border-slate-100 pt-2">
            {steps.map((step, i) => {
              const isLatest = i === steps.length - 1;
              return (
                <p
                  key={i}
                  className={`text-xs flex items-start gap-1.5 ${
                    isLatest ? 'text-slate-700 font-medium' : 'text-slate-400'
                  }`}
                >
                  <span className="mt-0.5 flex-shrink-0">{isLatest ? '→' : '✓'}</span>
                  <span>{step}</span>
                </p>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Chat page
// ---------------------------------------------------------------------------
const WELCOME_MESSAGE = {
  id: 0,
  role: 'agent',
  content: "Hi! I'm your lead intelligence agent. Ask me to find companies, show leads, check replies, or run the full pipeline.",
  data: null,
};

export default function Chat() {
  const [messages, setMessages] = useState(() => {
    try {
      const saved = localStorage.getItem('chat_messages');
      return saved ? JSON.parse(saved) : [WELCOME_MESSAGE];
    } catch {
      return [WELCOME_MESSAGE];
    }
  });
  const [input, setInput] = useState('');
  // If there's a run_id saved in sessionStorage, we were mid-run when user left
  const [loading, setLoading] = useState(
    () => !!sessionStorage.getItem('chat_active_run_id')
  );
  const [progressSteps, setProgressSteps] = useState([]);
  const pollingRef = useRef(null);
  const bottomRef = useRef(null);

  // Persist all messages (both sides) to localStorage whenever they change
  useEffect(() => {
    try {
      localStorage.setItem('chat_messages', JSON.stringify(messages));
    } catch {
      // localStorage full — silently skip
    }
  }, [messages]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading, progressSteps]);

  // Stop polling on unmount — but the run_id stays in sessionStorage
  // so when the user comes back, polling resumes automatically
  useEffect(() => {
    return () => {
      if (pollingRef.current) clearTimeout(pollingRef.current);
    };
  }, []);

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearTimeout(pollingRef.current);
      pollingRef.current = null;
    }
    sessionStorage.removeItem('chat_active_run_id');
  }, []);

  const finishRun = useCallback((reply, data, runId) => {
    stopPolling();
    setMessages((prev) => [
      ...prev,
      {
        id: Date.now(),
        role: 'agent',
        content: reply || 'Done.',
        data: data || null,
        runId,
      },
    ]);
    setProgressSteps([]);
    setLoading(false);
  }, [stopPolling]);

  const pollRun = useCallback(async (runId) => {
    try {
      const [runStatus, chatResult] = await Promise.allSettled([
        fetchRunStatus(runId),
        fetchChatResult(runId),
      ]);

      // Update live progress steps from DB logs
      if (runStatus.status === 'fulfilled' && runStatus.value?.recent_logs) {
        const steps = runStatus.value.recent_logs
          .map((lg) => lg.output_summary)
          .filter(Boolean);
        setProgressSteps(steps);
      }

      if (chatResult.status === 'fulfilled') {
        const result = chatResult.value;
        if (result.status === 'done' || result.status === 'error') {
          finishRun(result.reply, result.data, result.run_id);
          return;
        }
        // Still pending — keep polling
        pollingRef.current = setTimeout(() => pollRun(runId), 2000);
      } else {
        // fetchChatResult rejected — most likely 404 (server restarted)
        const msg = chatResult.reason?.message || '';
        if (msg.includes('404') || msg.includes('not found') || msg.includes('expired')) {
          finishRun(
            'The agent was still running when the server restarted. Please try your request again.',
            null,
            runId,
          );
        } else {
          // Network hiccup — retry
          pollingRef.current = setTimeout(() => pollRun(runId), 3000);
        }
      }
    } catch {
      pollingRef.current = setTimeout(() => pollRun(runId), 3000);
    }
  }, [finishRun]);

  // On mount: if there was an active run when user navigated away, resume polling
  useEffect(() => {
    const savedRunId = sessionStorage.getItem('chat_active_run_id');
    if (savedRunId) {
      pollingRef.current = setTimeout(() => pollRun(savedRunId), 500);
    }
  }, [pollRun]);

  async function handleSend(text) {
    const message = (text || input).trim();
    if (!message || loading) return;

    setInput('');
    setProgressSteps([]);
    setMessages((prev) => [...prev, { id: Date.now(), role: 'user', content: message }]);
    setLoading(true);

    try {
      const { run_id } = await startChat(message);
      // Persist run_id so polling can resume if user navigates away and back
      sessionStorage.setItem('chat_active_run_id', run_id);
      pollingRef.current = setTimeout(() => pollRun(run_id), 1000);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 1,
          role: 'agent',
          content: 'Could not start the agent — make sure the API is running (docker compose up).',
          data: null,
        },
      ]);
      setLoading(false);
    }
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  const showSuggestions = messages.length === 1;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="bg-white border-b border-slate-200 px-6 py-4 flex-shrink-0 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-slate-800">Chat Agent</h1>
          <p className="text-sm text-slate-500">Ask in natural language — agent decides what to do</p>
        </div>
        <button
          onClick={() => {
            stopPolling();
            localStorage.removeItem('chat_messages');
            setMessages([WELCOME_MESSAGE]);
            setLoading(false);
            setProgressSteps([]);
          }}
          className="text-xs text-slate-400 hover:text-slate-600 border border-slate-200 px-3 py-1.5 rounded-lg hover:border-slate-400 transition-colors"
        >
          Clear history
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {messages.map((msg) => (
          <Message key={msg.id} msg={msg} />
        ))}

        {loading && <ProgressIndicator steps={progressSteps} />}

        {/* Quick suggestions */}
        {showSuggestions && !loading && (
          <div className="mt-4">
            <p className="text-xs text-slate-400 mb-2 text-center">Try asking:</p>
            <div className="flex flex-wrap gap-2 justify-center">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => handleSend(s)}
                  className="text-xs bg-white border border-slate-200 text-slate-600 px-3 py-1.5 rounded-full hover:border-blue-400 hover:text-blue-600 transition-colors"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="bg-white border-t border-slate-200 px-6 py-4 flex-shrink-0">
        <div className="flex gap-3 items-end">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask me anything… e.g. find 10 healthcare companies in Buffalo NY"
            rows={1}
            disabled={loading}
            className="flex-1 resize-none border border-slate-300 rounded-xl px-4 py-3 text-sm text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50"
            style={{ minHeight: '44px', maxHeight: '120px' }}
          />
          <button
            onClick={() => handleSend()}
            disabled={!input.trim() || loading}
            className="bg-blue-600 hover:bg-blue-700 disabled:bg-slate-300 text-white px-5 py-3 rounded-xl text-sm font-medium transition-colors flex-shrink-0"
          >
            Send
          </button>
        </div>
        <p className="text-xs text-slate-400 mt-1.5">Press Enter to send · Shift+Enter for new line</p>
      </div>
    </div>
  );
}
