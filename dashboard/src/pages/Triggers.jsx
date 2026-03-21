/**
 * Triggers Page
 * 
 * Allows sales manager to manually control and trigger agent runs.
 * Supports full pipeline, scout-only, analyst-only, and writer-only modes.
 * Shows active trigger status with real-time polling.
 * 
 * Route: /triggers
 * 
 * Components:
 * - PageHeader: Title and subtitle
 * - RunFullPipelineCard: Full pipeline trigger with form
 * - RunScoutOnlyCard: Scout-only trigger with form
 * - RunAnalystOnlyCard: Analyst trigger (no form)
 * - RunWriterOnlyCard: Writer trigger (no form)
 * - ActiveRunStatus: Live status polling and progress
 * 
 * Usage:
 *   import Triggers from './pages/Triggers';
 *   <Route path="/triggers" element={<Triggers />} />
 */

import React, { useState, useEffect, useRef } from 'react';
import LoadingOverlay from '../components/LoadingOverlay';
import { useNavigate } from 'react-router-dom';
import {
  triggerFullPipeline,
  triggerScout,
  fetchTriggerStatus,
  fetchIndustries,
  fetchPipelineStatus,
} from '../services/api';

// ============================================================================
// UTILITIES
// ============================================================================

const BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8001';

/**
 * Make API call to trigger analyst
 */
async function triggerAnalyst() {
  const response = await fetch(`${BASE_URL}/trigger/analyst`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

/**
 * Make API call to trigger writer
 */
async function triggerWriter() {
  const response = await fetch(`${BASE_URL}/trigger/writer`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

/**
 * Format elapsed time in seconds
 */
function formatElapsedTime(seconds) {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${minutes}m ${secs}s`;
}

// ============================================================================
// SUB-COMPONENTS
// ============================================================================

/**
 * PageHeader: Title and subtitle
 */
function PageHeader() {
  return (
    <div className="mb-6">
      <h1 className="text-3xl font-bold text-gray-900">Pipeline Controls</h1>
      <p className="text-gray-600 mt-1">Manually trigger agent runs</p>
    </div>
  );
}

/**
 * RunFullPipelineCard: Full pipeline trigger with form
 */
function RunFullPipelineCard({ onTrigger, isLoading, disabled, knownIndustries }) {
  const [industry, setIndustry] = useState('healthcare');
  const [location, setLocation] = useState('Buffalo, NY');
  const [count, setCount] = useState(20);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!industry.trim() || !location.trim()) {
      alert('Please fill in all required fields');
      return;
    }
    onTrigger('full', { industry, location, count });
  };

  return (
    <div className="bg-white rounded-lg shadow p-6 mb-6">
      <h2 className="text-xl font-bold text-gray-900 mb-2">Run Full Pipeline</h2>
      <p className="text-gray-600 mb-4">
        Finds new companies, scores them, enriches contacts, and generates email drafts — all in one run.
      </p>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid md:grid-cols-2 gap-4">
          {/* Industry — free-type with DB suggestions */}
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-2">Industry *</label>
            <input
              type="text"
              list="full-industry-list"
              value={industry}
              onChange={(e) => setIndustry(e.target.value)}
              placeholder="e.g. healthcare, education, retail…"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <datalist id="full-industry-list">
              {knownIndustries.map((ind) => <option key={ind} value={ind} />)}
            </datalist>
          </div>

          {/* Location */}
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-2">Location *</label>
            <input
              type="text"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder="Buffalo, NY"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>

        {/* Count Slider */}
        <div>
          <label className="block text-sm font-semibold text-gray-700 mb-2">
            Find up to {count} companies
          </label>
          <input
            type="range"
            min="5"
            max="100"
            value={count}
            onChange={(e) => setCount(parseInt(e.target.value, 10))}
            className="w-full"
          />
          <div className="flex justify-between text-xs text-gray-500 mt-1">
            <span>5</span>
            <span>100</span>
          </div>
        </div>

        {/* Submit Button */}
        <button
          type="submit"
          disabled={isLoading || disabled}
          className="w-full px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400 transition font-semibold"
        >
          {isLoading ? '⏳ Running...' : '▶️ Run Full Pipeline'}
        </button>
      </form>

    </div>
  );
}

/**
 * RunScoutOnlyCard: Scout-only trigger with form
 */
function RunScoutOnlyCard({ onTrigger, isLoading, disabled, knownIndustries }) {
  const [industry, setIndustry] = useState('healthcare');
  const [location, setLocation] = useState('Buffalo, NY');
  const [count, setCount] = useState(20);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!industry.trim() || !location.trim()) {
      alert('Please fill in all required fields');
      return;
    }
    onTrigger('scout', { industry, location, count });
  };

  return (
    <div className="bg-white rounded-lg shadow p-6 mb-6">
      <h2 className="text-xl font-bold text-gray-900 mb-2">Scout Only — Find Companies</h2>
      <p className="text-gray-600 mb-4">Find new companies without scoring or emailing</p>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid md:grid-cols-2 gap-4">
          {/* Industry — free-type with DB suggestions */}
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-2">Industry *</label>
            <input
              type="text"
              list="scout-industry-list"
              value={industry}
              onChange={(e) => setIndustry(e.target.value)}
              placeholder="e.g. healthcare, education, retail…"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <datalist id="scout-industry-list">
              {knownIndustries.map((ind) => <option key={ind} value={ind} />)}
            </datalist>
          </div>

          {/* Location */}
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-2">Location *</label>
            <input
              type="text"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder="Buffalo, NY"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>

        {/* Count Slider */}
        <div>
          <label className="block text-sm font-semibold text-gray-700 mb-2">
            Find up to {count} companies
          </label>
          <input
            type="range"
            min="5"
            max="100"
            value={count}
            onChange={(e) => setCount(parseInt(e.target.value, 10))}
            className="w-full"
          />
          <div className="flex justify-between text-xs text-gray-500 mt-1">
            <span>5</span>
            <span>100</span>
          </div>
        </div>

        {/* Submit Button */}
        <button
          type="submit"
          disabled={isLoading || disabled}
          className="w-full px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:bg-gray-400 transition font-semibold"
        >
          {isLoading ? '⏳ Finding...' : '🔍 Find Companies'}
        </button>
      </form>

    </div>
  );
}

/**
 * RunAnalystOnlyCard: Analyst-only trigger
 */
function RunAnalystOnlyCard({ onTrigger, isLoading, disabled, pendingAnalystCount }) {
  const handleSubmit = (e) => {
    e.preventDefault();
    onTrigger('analyst', {});
  };

  return (
    <div className="bg-white rounded-lg shadow p-6 mb-6">
      <h2 className="text-xl font-bold text-gray-900 mb-2">Analyst Only — Score Pending Companies</h2>
      <p className="text-gray-600 mb-4">
        Score all companies that have been found but not yet analyzed
      </p>

      <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
        <p className="text-sm text-blue-900 font-semibold">
          {pendingAnalystCount} companies pending analysis
        </p>
      </div>

      <form onSubmit={handleSubmit}>
        <button
          type="submit"
          disabled={isLoading || disabled || pendingAnalystCount === 0}
          className="w-full px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:bg-gray-400 transition font-semibold"
        >
          {isLoading ? '⏳ Scoring...' : '⭐ Score Now'}
        </button>
      </form>

    </div>
  );
}

/**
 * RunWriterOnlyCard: Writer-only trigger
 */
function RunWriterOnlyCard({ onTrigger, isLoading, disabled, pendingWriterCount }) {
  const handleSubmit = (e) => {
    e.preventDefault();
    onTrigger('writer', {});
  };

  return (
    <div className="bg-white rounded-lg shadow p-6 mb-6">
      <h2 className="text-xl font-bold text-gray-900 mb-2">Writer Only — Generate Email Drafts</h2>
      <p className="text-gray-600 mb-4">
        Generate email drafts for all approved high-score leads that do not have drafts yet
      </p>

      <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
        <p className="text-sm text-blue-900 font-semibold">
          {pendingWriterCount} approved leads without email drafts
        </p>
      </div>

      <form onSubmit={handleSubmit}>
        <button
          type="submit"
          disabled={isLoading || disabled || pendingWriterCount === 0}
          className="w-full px-4 py-2 bg-orange-600 text-white rounded-lg hover:bg-orange-700 disabled:bg-gray-400 transition font-semibold"
        >
          {isLoading ? '⏳ Generating...' : '✉️ Generate Drafts'}
        </button>
      </form>

    </div>
  );
}

/**
 * ResultSummary: Show what was saved after a run completes
 */
function ResultSummary({ summary, runMode, navigate }) {
  if (!summary) return null;

  // Scout returns {company_ids: [...]}
  // Analyst returns {scored, high, medium, low, high_ids}
  // Full pipeline returns {companies_found, scored_high, scored_medium, contacts_found, drafts_created}
  const companiesFound = summary.companies_found ?? summary.scored ?? summary.company_ids?.length ?? 0;
  const scoredHigh = summary.scored_high ?? summary.high ?? 0;
  const scoredMedium = summary.scored_medium ?? summary.medium ?? 0;
  const drafts = summary.drafts_created ?? 0;
  const contacts = summary.contacts_found ?? 0;

  return (
    <div className="mt-3 bg-white border border-green-200 rounded-lg p-4">
      <p className="text-sm font-semibold text-green-800 mb-2">Run Results</p>
      <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm text-gray-700">
        <span>Companies saved:</span>
        <span className="font-semibold text-green-700">{companiesFound}</span>
        {(scoredHigh > 0 || scoredMedium > 0) && (
          <>
            <span>High tier:</span>
            <span className="font-semibold text-green-700">{scoredHigh}</span>
            <span>Medium tier:</span>
            <span className="font-semibold text-yellow-700">{scoredMedium}</span>
          </>
        )}
        {contacts > 0 && (
          <>
            <span>Contacts found:</span>
            <span className="font-semibold">{contacts}</span>
          </>
        )}
        {drafts > 0 && (
          <>
            <span>Email drafts:</span>
            <span className="font-semibold">{drafts}</span>
          </>
        )}
      </div>
      {companiesFound > 0 && (
        <button
          onClick={() => navigate('/leads')}
          className="mt-3 px-4 py-1.5 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 transition"
        >
          View in Leads page →
        </button>
      )}
    </div>
  );
}

/**
 * ActiveRunStatus: Live status with polling, shows result summary on completion
 */
function ActiveRunStatus({ triggerId, pollInterval = 3000, navigate, onComplete }) {
  const [status, setStatus] = useState(null);
  const [elapsedTime, setElapsedTime] = useState(0);
  const pollingRef = useRef(null);
  const timerRef = useRef(null);

  useEffect(() => {
    if (!triggerId) return;

    const startTime = Date.now();

    const pollStatus = async () => {
      try {
        const data = await fetchTriggerStatus(triggerId);
        setStatus(data);
        if (data.status === 'completed' || data.status === 'failed') {
          clearInterval(pollingRef.current);
          clearInterval(timerRef.current);
          if (onComplete) onComplete();
        }
      } catch (err) {
        console.error('Failed to fetch trigger status:', err);
      }
    };

    pollStatus();
    pollingRef.current = setInterval(pollStatus, pollInterval);
    timerRef.current = setInterval(() => {
      setElapsedTime(Math.floor((Date.now() - startTime) / 1000));
    }, 1000);

    return () => {
      clearInterval(pollingRef.current);
      clearInterval(timerRef.current);
    };
  }, [triggerId, pollInterval]);

  if (!status) return null;

  const colorMap = {
    running: 'bg-blue-50 border-blue-300 text-blue-900',
    completed: 'bg-green-50 border-green-300 text-green-900',
    failed: 'bg-red-50 border-red-300 text-red-900',
  };
  const colorClass = colorMap[status.status] || 'bg-gray-50 border-gray-200 text-gray-900';

  const progress = status.progress || [];
  const tierColor = (tier) => {
    if (tier === 'high') return 'text-green-700 font-semibold';
    if (tier === 'medium') return 'text-yellow-700 font-semibold';
    return 'text-gray-500';
  };

  return (
    <div className={`p-4 border rounded-lg ${colorClass} mb-6`}>
      <div className="flex justify-between items-center mb-1">
        <p className="font-bold">
          {status.status === 'running' && `⏳ Running… (${progress.length} processed)`}
          {status.status === 'completed' && '✅ Completed'}
          {status.status === 'failed' && '❌ Failed'}
        </p>
        <p className="text-sm font-mono">{formatElapsedTime(elapsedTime)}</p>
      </div>

      {status.status === 'failed' && (
        <p className="text-sm text-red-700 mt-1">{status.error_message || 'Unknown error'}</p>
      )}

      {/* Per-company progress log */}
      {progress.length > 0 && (
        <div className="mt-3 max-h-56 overflow-y-auto rounded border border-slate-200 bg-white text-xs font-mono">
          <table className="w-full">
            <thead className="sticky top-0 bg-slate-100 text-slate-500 text-left">
              <tr>
                <th className="px-2 py-1 w-8">#</th>
                <th className="px-2 py-1">Company</th>
                <th className="px-2 py-1 text-right">Score</th>
                <th className="px-2 py-1 text-right">Tier</th>
                <th className="px-2 py-1 text-right">Emp</th>
                <th className="px-2 py-1 text-right">Time</th>
              </tr>
            </thead>
            <tbody>
              {progress.map((p, i) => (
                <tr key={i} className={i % 2 === 0 ? 'bg-white' : 'bg-slate-50'}>
                  <td className="px-2 py-0.5 text-slate-400">{p.idx}</td>
                  <td className="px-2 py-0.5 truncate max-w-xs">
                    {p.status === 'failed'
                      ? <span className="text-red-500">✗ {p.name}</span>
                      : <span className="text-slate-700">✓ {p.name}</span>
                    }
                  </td>
                  <td className="px-2 py-0.5 text-right text-slate-600">{p.score ?? '—'}</td>
                  <td className={`px-2 py-0.5 text-right ${tierColor(p.tier)}`}>{p.tier ?? '—'}</td>
                  <td className="px-2 py-0.5 text-right text-slate-500">{p.employee_count ? p.employee_count.toLocaleString() : '—'}</td>
                  <td className="px-2 py-0.5 text-right text-slate-400">{p.duration_s ?? '—'}s</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {status.status === 'running' && progress.length === 0 && (
        <p className="text-sm mt-1">Starting — first company processing…</p>
      )}

      {status.status === 'completed' && (
        <ResultSummary
          summary={status.result_summary}
          runMode={status.run_mode}
          navigate={navigate}
        />
      )}
    </div>
  );
}

// ============================================================================
// MAIN COMPONENT
// ============================================================================

/**
 * Triggers: Pipeline control page
 */
export default function Triggers() {
  const navigate = useNavigate();
  const [isLoading, setIsLoading] = useState(false);
  const [isPageLoading, setIsPageLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeTrigger, setActiveTrigger] = useState(null);
  const [triggerStatus, setTriggerStatus] = useState(null);
  const [pendingCounts, setPendingCounts] = useState({ analyst: 0, writer: 0 });
  const [knownIndustries, setKnownIndustries] = useState([]);

  useEffect(() => {
    Promise.allSettled([
      fetchIndustries().then(setKnownIndustries).catch(() => {}),
      fetchPipelineStatus()
        .then((data) => {
          const pendingAnalyst = (data['new'] || 0) + (data['enriched'] || 0);
          const pendingWriter = data['approved'] || 0;
          setPendingCounts({ analyst: pendingAnalyst, writer: pendingWriter });
        })
        .catch((err) => console.warn('Pipeline status fetch failed:', err)),
    ]).finally(() => setIsPageLoading(false));
  }, []);

  /**
   * Handle trigger
   */
  const handleTrigger = async (mode, params) => {
    setIsLoading(true);
    setError(null);
    setTriggerStatus({ mode, status: 'starting', progress: '' });

    try {
      let response;

      switch (mode) {
        case 'full':
          response = await triggerFullPipeline(
            params.industry,
            params.location,
            params.count
          );
          break;
        case 'scout':
          response = await triggerScout(
            params.industry,
            params.location,
            params.count
          );
          break;
        case 'analyst':
          response = await triggerAnalyst();
          break;
        case 'writer':
          response = await triggerWriter();
          break;
        default:
          throw new Error(`Unknown trigger mode: ${mode}`);
      }

      setActiveTrigger(response.trigger_id);
      setTriggerStatus({
        mode,
        status: 'running',
        progress: response.message || 'Running...',
      });
    } catch (err) {
      console.error('Trigger failed:', err);
      setError(`Failed to trigger ${mode} run: ${err.message}`);
      setTriggerStatus({
        mode,
        status: 'failed',
        progress: err.message,
      });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto bg-gray-50 p-6">
      {(isPageLoading || isLoading) && <LoadingOverlay message={isPageLoading ? "Loading triggers..." : "Running agent..."} />}
      <div className="max-w-4xl mx-auto">
        <PageHeader />

        {error && (
          <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded-lg mb-6">
            {error}
          </div>
        )}

        <RunFullPipelineCard
          onTrigger={handleTrigger}
          isLoading={isLoading && triggerStatus?.mode === 'full'}
          disabled={!!activeTrigger}
          knownIndustries={knownIndustries}
        />
        {activeTrigger && triggerStatus?.mode === 'full' && (
          <ActiveRunStatus triggerId={activeTrigger} navigate={navigate} onComplete={() => setActiveTrigger(null)} />
        )}

        <RunScoutOnlyCard
          onTrigger={handleTrigger}
          isLoading={isLoading && triggerStatus?.mode === 'scout'}
          disabled={!!activeTrigger}
          knownIndustries={knownIndustries}
        />
        {activeTrigger && triggerStatus?.mode === 'scout' && (
          <ActiveRunStatus triggerId={activeTrigger} navigate={navigate} onComplete={() => setActiveTrigger(null)} />
        )}

        <RunAnalystOnlyCard
          onTrigger={handleTrigger}
          isLoading={isLoading && triggerStatus?.mode === 'analyst'}
          disabled={!!activeTrigger}
          pendingAnalystCount={pendingCounts.analyst}
        />
        {activeTrigger && triggerStatus?.mode === 'analyst' && (
          <ActiveRunStatus triggerId={activeTrigger} navigate={navigate} onComplete={() => setActiveTrigger(null)} />
        )}

        <RunWriterOnlyCard
          onTrigger={handleTrigger}
          isLoading={isLoading && triggerStatus?.mode === 'writer'}
          disabled={!!activeTrigger}
          pendingWriterCount={pendingCounts.writer}
        />
        {activeTrigger && triggerStatus?.mode === 'writer' && (
          <ActiveRunStatus triggerId={activeTrigger} navigate={navigate} onComplete={() => setActiveTrigger(null)} />
        )}
      </div>
    </div>
  );
}
