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
  triggerEnrich,
  triggerBackfillPhones,
  triggerVerifyEmails,
  triggerAutoApprove,
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
 * EnrichActiveStatus: Live per-company progress log for the enrich trigger.
 * Polls the same trigger status endpoint as ActiveRunStatus but shows
 * enrichment-specific columns: provider used, contacts found, phone scraped.
 */
function EnrichActiveStatus({ triggerId, onComplete }) {
  const [status, setStatus] = useState(null);
  const [elapsed, setElapsed] = useState(0);
  const pollingRef = useRef(null);
  const timerRef  = useRef(null);

  useEffect(() => {
    if (!triggerId) return;
    const startTime = Date.now();

    const poll = async () => {
      try {
        const data = await fetchTriggerStatus(triggerId);
        setStatus(data);
        if (data.status === 'completed' || data.status === 'failed' || data.status === 'not_found') {
          clearInterval(pollingRef.current);
          clearInterval(timerRef.current);
          if (onComplete) onComplete();
        }
      } catch {}
    };

    poll();
    pollingRef.current = setInterval(poll, 2500);
    timerRef.current   = setInterval(() => setElapsed(Math.floor((Date.now() - startTime) / 1000)), 1000);

    return () => { clearInterval(pollingRef.current); clearInterval(timerRef.current); };
  }, [triggerId]);

  if (!status) return null;

  const progress = status.progress || [];
  const total    = status.total ?? '?';
  const colorMap = {
    running:   'bg-orange-50 border-orange-300 text-orange-900',
    completed: 'bg-green-50 border-green-300 text-green-900',
    failed:    'bg-red-50 border-red-300 text-red-900',
  };

  const providerBadge = (p) => {
    const colors = {
      hunter:          'bg-blue-100 text-blue-700',
      apollo:          'bg-purple-100 text-purple-700',
      website_scraper: 'bg-yellow-100 text-yellow-700',
      serper:          'bg-green-100 text-green-700',
      serper_email:    'bg-emerald-100 text-emerald-700',
      snov:            'bg-pink-100 text-pink-700',
      prospeo:         'bg-rose-100 text-rose-700',
    };
    return colors[p] || 'bg-gray-100 text-gray-600';
  };

  const rowIcon = (s) => {
    if (s === 'found')     return <span className="text-green-600">✓</span>;
    if (s === 'not_found') return <span className="text-gray-400">—</span>;
    if (s === 'failed')    return <span className="text-red-500">✗</span>;
    return <span className="text-gray-400">·</span>;
  };

  return (
    <div className={`p-4 border rounded-lg mb-4 ${colorMap[status.status] || 'bg-gray-50 border-gray-200'}`}>
      <div className="flex justify-between items-center mb-2">
        <p className="font-bold text-sm">
          {status.status === 'running'   && `⏳ Enriching… ${progress.length}/${total} companies`}
          {status.status === 'completed' && `✅ Done — ${status.result_summary?.contacts_found ?? 0} contacts found`}
          {status.status === 'failed'    && '❌ Enrichment failed'}
        </p>
        <p className="text-xs font-mono text-gray-500">{formatElapsedTime(elapsed)}</p>
      </div>

      {status.status === 'failed' && (
        <p className="text-sm text-red-700 mb-2">{status.error_message}</p>
      )}

      {/* Per-company live log */}
      {progress.length > 0 && (
        <div className="mt-2 max-h-56 overflow-y-auto rounded border border-orange-200 bg-white text-xs font-mono">
          <table className="w-full">
            <thead className="sticky top-0 bg-slate-100 text-slate-500 text-left">
              <tr>
                <th className="px-2 py-1 w-6">#</th>
                <th className="px-2 py-1">Company</th>
                <th className="px-2 py-1 text-center">Contacts</th>
                <th className="px-2 py-1 text-center">Provider</th>
                <th className="px-2 py-1 text-center">Phone</th>
              </tr>
            </thead>
            <tbody>
              {progress.map((p, i) => (
                <tr key={i} className={i % 2 === 0 ? 'bg-white' : 'bg-slate-50'}>
                  <td className="px-2 py-0.5 text-slate-400">{p.idx}</td>
                  <td className="px-2 py-0.5 truncate max-w-[200px] text-slate-700">
                    {rowIcon(p.status)} {p.name}
                  </td>
                  <td className="px-2 py-0.5 text-center">
                    {p.contacts_found > 0
                      ? <span className="text-green-700 font-semibold">{p.contacts_found}</span>
                      : <span className="text-gray-400">0</span>
                    }
                  </td>
                  <td className="px-2 py-0.5 text-center">
                    {p.provider
                      ? <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${providerBadge(p.provider)}`}>{p.provider}</span>
                      : <span className="text-gray-400">—</span>
                    }
                  </td>
                  <td className="px-2 py-0.5 text-center">
                    {p.has_phone ? '📞' : <span className="text-gray-300">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {status.status === 'running' && progress.length === 0 && (
        <p className="text-sm text-orange-700 mt-1">Starting — first company processing…</p>
      )}
    </div>
  );
}

/**
 * RunEnrichContactsCard: Enrich contacts for scored/approved companies
 */
function RunEnrichContactsCard({ onTrigger, onBackfillPhones, isLoading, isLoadingPhones, isLoadingVerify, enrichResult, phonesResult, verifyResult, pipelineData, disabled }) {
  const contactsWith   = pipelineData?.contacts_with   ?? 0;
  const contactsNeeded = pipelineData?.contacts_needed ?? 0;
  const total = contactsWith + contactsNeeded;
  const pct   = total > 0 ? Math.round((contactsWith / total) * 100) : 0;

  return (
    <div className="bg-white rounded-lg shadow p-6 mb-6">
      <h2 className="text-xl font-bold text-gray-900 mb-2">👤 Enrich Contacts</h2>
      <p className="text-gray-600 mb-4">
        Find decision-maker contacts for <strong>approved</strong> companies only.
        Waterfall: Hunter → Apollo → Website scraper → Serper → Prospeo → ZeroBounce → 8-pattern permutation.
      </p>

      {/* Coverage progress */}
      {total > 0 && (
        <div className="mb-4 p-3 bg-orange-50 border border-orange-200 rounded-lg">
          <div className="flex justify-between text-sm mb-1">
            <span className="font-semibold text-orange-900">Contact coverage</span>
            <span className="text-orange-700 font-semibold">{pct}% ({contactsWith}/{total})</span>
          </div>
          <div className="h-2 bg-orange-100 rounded-full overflow-hidden">
            <div className="h-2 bg-orange-500 rounded-full transition-all duration-500" style={{ width: `${pct}%` }} />
          </div>
          <p className="text-xs text-orange-700 mt-1">
            {contactsWith} enriched · <span className="font-semibold">{contactsNeeded} remaining</span>
          </p>
        </div>
      )}

      <div className="flex gap-3">
        <button
          onClick={() => onTrigger('enrich', {})}
          disabled={isLoading || disabled || contactsNeeded === 0}
          className="flex-1 px-4 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600 disabled:bg-gray-400 transition font-semibold"
        >
          {isLoading ? '⏳ Enriching...' : contactsNeeded === 0 ? '✓ All enriched' : `▶ Enrich Contacts (${contactsNeeded})`}
        </button>
        <button
          onClick={() => onTrigger('backfill_phones', {})}
          disabled={isLoadingPhones || disabled}
          className="px-4 py-2 bg-teal-600 text-white rounded-lg hover:bg-teal-700 disabled:bg-gray-400 transition font-semibold"
          title="Scrape phone numbers from company websites"
        >
          {isLoadingPhones ? '⏳ Scraping...' : '📞 Backfill Phones'}
        </button>
        <button
          onClick={() => onTrigger('verify_emails', {})}
          disabled={isLoadingVerify || disabled}
          className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:bg-gray-400 transition font-semibold"
          title="Verify unverified emails via ZeroBounce"
        >
          {isLoadingVerify ? '⏳ Verifying...' : '✔ Verify Emails'}
        </button>
      </div>

      {/* Verify emails result */}
      {verifyResult && !isLoadingVerify && (
        <div className={`mt-3 p-3 rounded-lg border text-sm ${verifyResult.failed ? 'bg-red-50 border-red-200 text-red-700' : 'bg-purple-50 border-purple-200 text-purple-800'}`}>
          {verifyResult.failed
            ? `✗ Verification failed: ${verifyResult.error || 'Unknown error'}`
            : verifyResult.noCredits > 0
              ? `⚠ No credits — Hunter & ZeroBounce both exhausted. ${verifyResult.noCredits}/${verifyResult.total} contacts unchanged. Wait for monthly reset then re-run.`
              : `✔ ${verifyResult.verified} verified · ${verifyResult.invalid} invalid · ${verifyResult.total} checked · ${verifyResult.skipped ?? 0} generic inboxes skipped (credits saved)`}
        </div>
      )}

      {/* Enrich result */}
      {enrichResult && !isLoading && (
        <div className={`mt-3 p-3 rounded-lg border text-sm ${
          enrichResult.failed
            ? 'bg-red-50 border-red-200 text-red-700'
            : enrichResult.contacts_found > 0
              ? 'bg-green-50 border-green-200 text-green-800'
              : 'bg-yellow-50 border-yellow-200 text-yellow-800'
        }`}>
          {enrichResult.failed
            ? `✗ Enrichment failed: ${enrichResult.error || 'Unknown error'}`
            : enrichResult.contacts_found > 0
              ? `✓ ${enrichResult.contacts_found} new contact${enrichResult.contacts_found !== 1 ? 's' : ''} found`
              : 'Run complete — no new contacts found'}
        </div>
      )}

      {/* Phone backfill result */}
      {phonesResult && !isLoadingPhones && (
        <div className={`mt-2 p-3 rounded-lg border text-sm ${phonesResult.failed ? 'bg-red-50 border-red-200 text-red-700' : phonesResult.phones_filled > 0 ? 'bg-teal-50 border-teal-200 text-teal-800' : 'bg-yellow-50 border-yellow-200 text-yellow-800'}`}>
          {phonesResult.failed
            ? `Phone backfill failed: ${phonesResult.error || 'Unknown error'}`
            : phonesResult.phones_filled > 0
              ? `✓ ${phonesResult.phones_filled} phone${phonesResult.phones_filled !== 1 ? 's' : ''} added from ${phonesResult.companies_checked} companies`
              : `Checked ${phonesResult.companies_checked} companies — no phone numbers found`}
        </div>
      )}
    </div>
  );
}

/**
 * ResultSummary: Show what was saved after a run completes
 */
function ResultSummary({ summary, runMode, navigate }) {
  if (!summary) return null;

  // Writer run — show draft-specific result
  if (runMode === 'writer' || runMode === 'writer_only') {
    const drafts = summary.drafts_created ?? 0;
    return (
      <div className="mt-3 bg-white border border-green-200 rounded-lg p-4">
        <p className="text-sm font-semibold text-green-800 mb-2">Run Results</p>
        {drafts > 0 ? (
          <>
            <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm text-gray-700">
              <span>Email drafts created:</span>
              <span className="font-semibold text-green-700">{drafts}</span>
            </div>
            <button
              onClick={() => navigate('/emails')}
              className="mt-3 px-4 py-1.5 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 transition"
            >
              Review drafts →
            </button>
          </>
        ) : (
          <p className="text-sm text-gray-600">
            No drafts created. Make sure there are approved companies with no existing draft
            — approve leads on the <button onClick={() => navigate('/leads')} className="text-blue-600 underline">Leads page</button> first.
          </p>
        )}
      </div>
    );
  }

  // Scout / Analyst / Full pipeline
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
        if (data.status === 'completed' || data.status === 'failed' || data.status === 'not_found') {
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
  const isWriter = status.run_mode === 'writer_only' || status.run_mode === 'writer';

  // For writer: deduplicate by idx, keep latest step per company
  const writerRows = (() => {
    if (!isWriter) return [];
    const map = {};
    for (const e of progress) {
      map[e.idx] = e; // later entries overwrite earlier ones for same company
    }
    return Object.values(map).sort((a, b) => a.idx - b.idx);
  })();

  // Use upfront total from registry if available, fall back to rows seen so far
  const writerDone = writerRows.filter(r => r.done).length;
  const writerTotal = status.total || writerRows.length;

  const tierColor = (tier) => {
    if (tier === 'high') return 'text-green-700 font-semibold';
    if (tier === 'medium') return 'text-yellow-700 font-semibold';
    return 'text-gray-500';
  };

  return (
    <div className={`p-4 border rounded-lg ${colorClass} mb-6`}>
      <div className="flex justify-between items-center mb-1">
        <p className="font-bold">
          {status.status === 'running' && (
            isWriter
              ? `⏳ Writing drafts… (${writerDone} / ${writerTotal || '?'} done)`
              : `⏳ Running… (${progress.length} processed)`
          )}
          {status.status === 'completed' && '✅ Completed'}
          {status.status === 'failed' && '❌ Failed'}
        </p>
        <p className="text-sm font-mono">{formatElapsedTime(elapsedTime)}</p>
      </div>

      {status.status === 'failed' && (
        <p className="text-sm text-red-700 mt-1">{status.error_message || 'Unknown error'}</p>
      )}

      {/* Writer-specific step progress */}
      {isWriter && writerRows.length > 0 && (
        <div className="mt-3 max-h-64 overflow-y-auto rounded border border-blue-200 bg-white text-xs font-mono">
          <table className="w-full">
            <thead className="sticky top-0 bg-slate-100 text-slate-500 text-left">
              <tr>
                <th className="px-2 py-1 w-6">#</th>
                <th className="px-2 py-1">Company</th>
                <th className="px-2 py-1">Current Step</th>
                <th className="px-2 py-1 text-center">AI Score</th>
                <th className="px-2 py-1 text-center">Rewrites</th>
              </tr>
            </thead>
            <tbody>
              {writerRows.map((r, i) => (
                <tr key={r.idx} className={i % 2 === 0 ? 'bg-white' : 'bg-slate-50'}>
                  <td className="px-2 py-1 text-slate-400">{r.idx}</td>
                  <td className="px-2 py-1 truncate max-w-[180px] text-slate-700 font-medium">{r.name}</td>
                  <td className="px-2 py-1">
                    {r.done ? (
                      r.step === '✅ Done'
                        ? <span className="text-green-700 font-semibold">✅ Done</span>
                        : r.step === '⚠️ Low confidence'
                          ? <span className="text-yellow-600 font-semibold">⚠️ Low confidence</span>
                          : <span className="text-red-500">{r.step}</span>
                    ) : (
                      <span className="text-blue-600 animate-pulse">{r.step}</span>
                    )}
                  </td>
                  <td className="px-2 py-1 text-center">
                    {r.critic_score != null
                      ? <span className={r.critic_score >= 7 ? 'text-green-700 font-semibold' : 'text-yellow-600'}>{r.critic_score}/10</span>
                      : <span className="text-slate-300">—</span>
                    }
                  </td>
                  <td className="px-2 py-1 text-center text-slate-500">{r.rewrites ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Non-writer per-company progress log */}
      {!isWriter && progress.length > 0 && (
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
  const [isLoading,       setIsLoading]       = useState(false);
  const [isPageLoading,   setIsPageLoading]   = useState(true);
  const [isLoadingEnrich, setIsLoadingEnrich] = useState(false);
  const [isLoadingPhones, setIsLoadingPhones] = useState(false);
  const [isLoadingVerify,      setIsLoadingVerify]      = useState(false);
  const [verifyResult,         setVerifyResult]         = useState(null);
  const [isLoadingAutoApprove, setIsLoadingAutoApprove] = useState(false);
  const [autoApproveResult,    setAutoApproveResult]    = useState(null);
  const [error,           setError]           = useState(null);
  const [activeTrigger,   setActiveTrigger]   = useState(null);
  const [isRunning,       setIsRunning]       = useState(false);
  const [triggerStatus,   setTriggerStatus]   = useState(null);
  const [enrichResult,    setEnrichResult]    = useState(null); // { contacts_found, failed }
  const [enrichTriggerId, setEnrichTriggerId] = useState(null); // for live progress polling
  const [phonesResult,    setPhonesResult]    = useState(null); // { phones_filled, companies_checked, failed }
  const [pendingCounts,   setPendingCounts]   = useState({ analyst: 0, writer: 0 });
  const [pipelineData,    setPipelineData]    = useState(null);
  const [knownIndustries, setKnownIndustries] = useState([]);

  const refreshPendingCounts = () => {
    fetchPipelineStatus()
      .then((data) => {
        const pendingAnalyst = (data['new'] || 0) + (data['enriched'] || 0);
        const pendingWriter = data['pending_writer'] ?? data['approved'] ?? 0;
        setPendingCounts({ analyst: pendingAnalyst, writer: pendingWriter });
        setPipelineData(data);
      })
      .catch((err) => console.warn('Pipeline status fetch failed:', err));
  };

  useEffect(() => {
    Promise.allSettled([
      fetchIndustries().then(setKnownIndustries).catch(() => {}),
      fetchPipelineStatus()
        .then((data) => {
          const pendingAnalyst = (data['new'] || 0) + (data['enriched'] || 0);
          const pendingWriter = data['pending_writer'] ?? data['approved'] ?? 0;
          setPendingCounts({ analyst: pendingAnalyst, writer: pendingWriter });
          setPipelineData(data);
        })
        .catch((err) => console.warn('Pipeline status fetch failed:', err)),
    ]).finally(() => setIsPageLoading(false));
  }, []);

  /**
   * Poll a trigger_id until completed/failed, then call onDone(result_summary).
   * Used by enrich and backfill_phones which have their own result state.
   */
  const pollUntilDone = (trigger_id, _unused, onDone) => {
    // Poll every 3s with no timeout — stops only when backend says completed or failed.
    const interval = setInterval(async () => {
      try {
        const data = await fetchTriggerStatus(trigger_id);
        if (data.status === 'completed') {
          clearInterval(interval);
          onDone({ ok: true, summary: data.result_summary });
          refreshPendingCounts();
        } else if (data.status === 'failed') {
          clearInterval(interval);
          onDone({ ok: false, error: data.error_message || 'Job failed on the server' });
        } else if (data.status === 'not_found') {
          clearInterval(interval);
          onDone({ ok: false, error: 'Server restarted — job lost. Please run again.' });
        }
        // still 'running' → keep polling
      } catch {
        // network blip — keep polling, don't stop
      }
    }, 3000);
  };

  /**
   * Handle trigger for full / scout / analyst / writer (uses ActiveRunStatus polling)
   * Enrich and backfill_phones are handled separately with their own result state.
   */
  const handleTrigger = async (mode, params) => {
    // Enrich contacts — uses its own state, not ActiveRunStatus
    if (mode === 'enrich') {
      setIsLoadingEnrich(true);
      setEnrichResult(null);
      setEnrichTriggerId(null);
      try {
        const { trigger_id } = await triggerEnrich();
        setEnrichTriggerId(trigger_id);
        pollUntilDone(trigger_id, 360, ({ ok, summary, error }) => {
          setEnrichResult(ok
            ? { contacts_found: summary?.contacts_found ?? 0, failed: false }
            : { contacts_found: 0, failed: error === 'Timed out', timedOut: error === 'Timed out', error });
          setIsLoadingEnrich(false);
        });
      } catch (err) {
        setEnrichResult({ contacts_found: 0, failed: true, error: err.message });
        setIsLoadingEnrich(false);
      }
      return;
    }

    // Backfill phones — uses its own state
    if (mode === 'backfill_phones') {
      setIsLoadingPhones(true);
      setPhonesResult(null);
      try {
        const { trigger_id } = await triggerBackfillPhones();
        pollUntilDone(trigger_id, 120, ({ ok, summary, error }) => {
          setPhonesResult(ok
            ? { phones_filled: summary?.phones_filled ?? 0, companies_checked: summary?.companies_checked ?? 0, failed: false }
            : { phones_filled: 0, companies_checked: 0, failed: true, error });
          setIsLoadingPhones(false);
        });
      } catch (err) {
        setPhonesResult({ phones_filled: 0, companies_checked: 0, failed: true, error: err.message });
        setIsLoadingPhones(false);
      }
      return;
    }

    // Verify emails — uses its own state
    if (mode === 'verify_emails') {
      setIsLoadingVerify(true);
      setVerifyResult(null);
      try {
        const { trigger_id } = await triggerVerifyEmails();
        pollUntilDone(trigger_id, null, ({ ok, summary, error }) => {
          setVerifyResult(ok
            ? { verified: summary?.verified ?? 0, invalid: summary?.invalid ?? 0, noCredits: summary?.no_credits ?? 0, total: summary?.total_checked ?? 0, skipped: summary?.skipped_generics ?? 0, failed: false }
            : { failed: true, error });
          setIsLoadingVerify(false);
        });
      } catch (err) {
        setVerifyResult({ failed: true, error: err.message });
        setIsLoadingVerify(false);
      }
      return;
    }

    // Auto-approve companies that already have a contact
    if (mode === 'auto_approve') {
      setIsLoadingAutoApprove(true);
      setAutoApproveResult(null);
      try {
        const { trigger_id } = await triggerAutoApprove();
        pollUntilDone(trigger_id, null, ({ ok, summary, error }) => {
          setAutoApproveResult(ok
            ? { approved: summary?.approved ?? 0, failed: false }
            : { failed: true, error });
          setIsLoadingAutoApprove(false);
          refreshPendingCounts();
        });
      } catch (err) {
        setAutoApproveResult({ failed: true, error: err.message });
        setIsLoadingAutoApprove(false);
      }
      return;
    }

    // Full / scout / analyst / writer — use ActiveRunStatus live log
    setIsLoading(true);
    setIsRunning(true);
    setActiveTrigger(null);
    setError(null);
    setTriggerStatus({ mode, status: 'starting', progress: '' });

    try {
      let response;
      switch (mode) {
        case 'full':
          response = await triggerFullPipeline(params.industry, params.location, params.count);
          break;
        case 'scout':
          response = await triggerScout(params.industry, params.location, params.count);
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
      setTriggerStatus({ mode, status: 'running', progress: response.message || 'Running...' });
    } catch (err) {
      console.error('Trigger failed:', err);
      setIsRunning(false);
      setError(`Failed to trigger ${mode} run: ${err.message}`);
      setTriggerStatus({ mode, status: 'failed', progress: err.message });
    } finally {
      setIsLoading(false);
    }
  };

  // Called by ActiveRunStatus when polling detects completed/failed
  const handleRunComplete = () => {
    setIsRunning(false);
    refreshPendingCounts();
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
          disabled={isRunning}
          knownIndustries={knownIndustries}
        />
        {activeTrigger && triggerStatus?.mode === 'full' && (
          <ActiveRunStatus triggerId={activeTrigger} navigate={navigate} onComplete={handleRunComplete} />
        )}

        <RunScoutOnlyCard
          onTrigger={handleTrigger}
          isLoading={isLoading && triggerStatus?.mode === 'scout'}
          disabled={isRunning}
          knownIndustries={knownIndustries}
        />
        {activeTrigger && triggerStatus?.mode === 'scout' && (
          <ActiveRunStatus triggerId={activeTrigger} navigate={navigate} onComplete={handleRunComplete} />
        )}

        <RunAnalystOnlyCard
          onTrigger={handleTrigger}
          isLoading={isLoading && triggerStatus?.mode === 'analyst'}
          disabled={isRunning}
          pendingAnalystCount={pendingCounts.analyst}
        />
        {activeTrigger && triggerStatus?.mode === 'analyst' && (
          <ActiveRunStatus triggerId={activeTrigger} navigate={navigate} onComplete={handleRunComplete} />
        )}

        <RunEnrichContactsCard
          onTrigger={handleTrigger}
          isLoading={isLoadingEnrich}
          isLoadingPhones={isLoadingPhones}
          isLoadingVerify={isLoadingVerify}
          enrichResult={enrichResult}
          phonesResult={phonesResult}
          verifyResult={verifyResult}
          pipelineData={pipelineData}
          disabled={isRunning}
        />
        {enrichTriggerId && (
          <EnrichActiveStatus
            triggerId={enrichTriggerId}
            onComplete={refreshPendingCounts}
          />
        )}

        <RunWriterOnlyCard
          onTrigger={handleTrigger}
          isLoading={isLoading && triggerStatus?.mode === 'writer'}
          disabled={isRunning}
          pendingWriterCount={pendingCounts.writer}
        />
        {activeTrigger && triggerStatus?.mode === 'writer' && (
          <ActiveRunStatus triggerId={activeTrigger} navigate={navigate} onComplete={handleRunComplete} />
        )}
      </div>
    </div>
  );
}
