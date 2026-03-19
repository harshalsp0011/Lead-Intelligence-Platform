/**
 * Scout Live Page
 *
 * Lets the user trigger a Scout run and watch companies appear in real time.
 * - Form: industry + location + count → POST /trigger/scout
 * - Polls GET /trigger/{id}/status every 3s while running
 * - Polls GET /leads every 3s to show newly found companies as cards
 * - Shows PipelineStatusBar with active stage = 'scout'
 *
 * Companies appear as cards as soon as they land in the DB.
 */

import React, { useState, useEffect, useRef } from 'react';
import PipelineStatusBar from '../components/PipelineStatusBar';
import { triggerScout, fetchTriggerStatus, fetchLeads } from '../services/api';

// ---------------------------------------------------------------------------
// Company card
// ---------------------------------------------------------------------------
function LiveCompanyCard({ company }) {
  const tierColor = {
    high:   'bg-green-100 text-green-700',
    medium: 'bg-yellow-100 text-yellow-700',
    low:    'bg-slate-100 text-slate-600',
  }[company.tier] || 'bg-slate-100 text-slate-500';

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-4 shadow-sm hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between gap-2">
        <p className="font-semibold text-slate-800 truncate">{company.name}</p>
        {company.tier && (
          <span className={`text-xs px-2 py-0.5 rounded-full flex-shrink-0 ${tierColor}`}>
            {company.tier}
          </span>
        )}
      </div>

      <p className="text-sm text-slate-500 mt-0.5">
        {company.industry} · {company.city}{company.state ? `, ${company.state}` : ''}
      </p>

      {company.website && (
        <a
          href={company.website}
          target="_blank"
          rel="noreferrer"
          className="text-xs text-blue-500 hover:underline mt-1 block truncate"
        >
          {company.website}
        </a>
      )}

      <div className="flex items-center gap-2 mt-2">
        <span className="text-xs bg-slate-100 text-slate-500 px-2 py-0.5 rounded">
          {company.source || 'scraped'}
        </span>
        {company.score != null && (
          <span className="text-xs text-slate-600 font-medium">
            Score: {Number(company.score).toFixed(1)}
          </span>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------
function EmptyState({ triggered }) {
  if (!triggered) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-slate-400">
        <span className="text-5xl mb-3">🔍</span>
        <p className="text-sm">Fill in the form above and click Start to find companies.</p>
      </div>
    );
  }
  return (
    <div className="flex flex-col items-center justify-center py-16 text-slate-400">
      <div className="flex gap-1.5 mb-3">
        <div className="w-2.5 h-2.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
        <div className="w-2.5 h-2.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
        <div className="w-2.5 h-2.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
      </div>
      <p className="text-sm">Searching for companies…</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main ScoutLive page
// ---------------------------------------------------------------------------
export default function ScoutLive() {
  const [industry, setIndustry]   = useState('healthcare');
  const [location, setLocation]   = useState('Buffalo NY');
  const [count, setCount]         = useState(10);

  const [runState, setRunState]   = useState('idle'); // idle | running | completed | failed
  const [triggerId, setTriggerId] = useState(null);
  const [companies, setCompanies] = useState([]);
  const [error, setError]         = useState(null);
  const [lastFetchedAt, setLastFetchedAt] = useState(null);

  const pollRef = useRef(null);

  // Stop polling on unmount
  useEffect(() => () => clearInterval(pollRef.current), []);

  async function handleStart(e) {
    e.preventDefault();
    setError(null);
    setCompanies([]);
    setRunState('running');

    try {
      const res = await triggerScout(industry, location, Number(count));
      setTriggerId(res.trigger_id);
      startPolling(res.trigger_id);
    } catch (err) {
      setError('Could not start Scout. Make sure the API is running.');
      setRunState('failed');
    }
  }

  function startPolling(tid) {
    // Clear any existing interval
    clearInterval(pollRef.current);

    pollRef.current = setInterval(async () => {
      try {
        // 1. Check trigger status
        const status = await fetchTriggerStatus(tid);
        if (status.status === 'completed' || status.status === 'failed') {
          clearInterval(pollRef.current);
          setRunState(status.status);
          if (status.status === 'failed') {
            setError(status.error_message || 'Scout run failed.');
          }
        }

        // 2. Fetch latest companies (always, so cards appear live)
        const leads = await fetchLeads({ page: 1, page_size: 50 });
        const items = leads.leads || leads.items || leads || [];
        setCompanies(items);
        setLastFetchedAt(new Date());
      } catch (err) {
        // Don't stop on transient fetch errors — just keep polling
      }
    }, 3000);
  }

  function handleReset() {
    clearInterval(pollRef.current);
    setRunState('idle');
    setTriggerId(null);
    setCompanies([]);
    setError(null);
    setLastFetchedAt(null);
  }

  const isRunning  = runState === 'running';
  const triggered  = runState !== 'idle';

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="bg-white border-b border-slate-200 px-6 py-4 flex-shrink-0">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold text-slate-800">Scout Live</h1>
            <p className="text-sm text-slate-500">Find companies and watch them appear in real time</p>
          </div>
          {triggered && (
            <button
              onClick={handleReset}
              className="text-xs text-slate-500 hover:text-slate-800 border border-slate-300 px-3 py-1.5 rounded-lg transition-colors"
            >
              New Search
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {/* Pipeline status bar */}
        <PipelineStatusBar
          activeStage={isRunning ? 'scout' : null}
          status={runState}
          counts={{ companies_found: companies.length }}
        />

        {/* Trigger form — hide once running */}
        {!triggered && (
          <form
            onSubmit={handleStart}
            className="bg-white border border-slate-200 rounded-lg p-5 flex flex-wrap gap-4 items-end"
          >
            <div className="flex flex-col gap-1 min-w-[140px]">
              <label className="text-xs font-medium text-slate-600">Industry</label>
              <input
                type="text"
                value={industry}
                onChange={(e) => setIndustry(e.target.value)}
                placeholder="e.g. healthcare"
                required
                className="border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div className="flex flex-col gap-1 min-w-[160px]">
              <label className="text-xs font-medium text-slate-600">Location</label>
              <input
                type="text"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
                placeholder="e.g. Buffalo NY"
                required
                className="border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div className="flex flex-col gap-1 w-24">
              <label className="text-xs font-medium text-slate-600">Count</label>
              <input
                type="number"
                value={count}
                onChange={(e) => setCount(e.target.value)}
                min={1}
                max={100}
                required
                className="border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <button
              type="submit"
              className="bg-blue-600 hover:bg-blue-700 text-white px-5 py-2 rounded-lg text-sm font-medium transition-colors"
            >
              Start Scout
            </button>
          </form>
        )}

        {/* Active run banner */}
        {isRunning && (
          <div className="bg-blue-50 border border-blue-200 rounded-lg px-4 py-3 flex items-center gap-3 text-sm text-blue-700">
            <div className="flex gap-1">
              <div className="w-2 h-2 bg-blue-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
              <div className="w-2 h-2 bg-blue-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
              <div className="w-2 h-2 bg-blue-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
            </div>
            <span>
              Scouting <strong>{industry}</strong> companies in <strong>{location}</strong>…
              {lastFetchedAt && (
                <span className="text-blue-500 ml-2 text-xs">
                  Updated {lastFetchedAt.toLocaleTimeString()}
                </span>
              )}
            </span>
          </div>
        )}

        {/* Completed banner */}
        {runState === 'completed' && (
          <div className="bg-green-50 border border-green-200 rounded-lg px-4 py-3 text-sm text-green-700">
            Scout completed — found <strong>{companies.length}</strong> companies.
            {' '}Go to the <a href="/leads" className="underline">Leads page</a> to score and approve them.
          </div>
        )}

        {/* Error banner */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {/* Company cards */}
        {companies.length > 0 ? (
          <div>
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
              Companies ({companies.length})
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {companies.map((c) => (
                <LiveCompanyCard key={c.company_id || c.id} company={c} />
              ))}
            </div>
          </div>
        ) : (
          <EmptyState triggered={triggered} />
        )}
      </div>
    </div>
  );
}
