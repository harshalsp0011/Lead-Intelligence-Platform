/**
 * Pipeline Overview Page — Status & Health Only
 *
 * Read-only view of the pipeline state. No trigger buttons here —
 * all controls live on the Triggers page (/triggers).
 *
 * Shows:
 * - Agent health bar
 * - Stage counts by status
 * - Pipeline value banner
 * - Hot leads alert
 * - Analyst status card  (pending count, no button)
 * - Enrich contacts card (coverage progress bar, no button)
 * - Recent activity feed
 */

import React, { useState, useEffect } from 'react';
import LoadingOverlay from '../components/LoadingOverlay';
import { useNavigate } from 'react-router-dom';
import {
  fetchPipelineStatus,
  fetchAgentHealth,
  fetchRecentActivity,
  fetchPendingEmails,
} from '../services/api';

// ============================================================================
// UTILITIES
// ============================================================================

function formatTimeAgo(timestamp) {
  const now = new Date();
  const then = new Date(timestamp);
  const seconds = Math.floor((now - then) / 1000);
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;
  return then.toLocaleDateString();
}

function getEventIcon(eventType) {
  const icons = {
    company_found:  { icon: '🔍', label: 'Found',  color: 'bg-gray-100'  },
    scored_high:    { icon: '⭐', label: 'Scored',  color: 'bg-green-100' },
    email_sent:     { icon: '✉️', label: 'Sent',    color: 'bg-blue-100'  },
    email_opened:   { icon: '👁️', label: 'Opened',  color: 'bg-yellow-100'},
    reply_received: { icon: '💬', label: 'Reply',   color: 'bg-red-100'   },
  };
  return icons[eventType] || { icon: '•', label: 'Event', color: 'bg-gray-100' };
}

function formatCurrency(value) {
  if (!value) return '$0';
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000)     return `$${(value / 1_000).toFixed(0)}k`;
  return `$${value}`;
}

// ============================================================================
// SUB-COMPONENTS
// ============================================================================

function PageHeader({ onRefresh, isLoading, lastUpdated }) {
  return (
    <div className="flex justify-between items-start mb-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Pipeline Overview</h1>
        <p className="text-gray-600 mt-1">Live lead generation status for Troy &amp; Banks</p>
      </div>
      <div className="text-right">
        <p className="text-sm text-gray-500 mb-2">
          Last updated: {lastUpdated ? lastUpdated.toLocaleTimeString() : '—'}
        </p>
        <button
          onClick={onRefresh}
          disabled={isLoading}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400 transition"
        >
          {isLoading ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>
    </div>
  );
}

function AgentHealthBar({ health, isLoading }) {
  const services = [
    { key: 'postgres',  label: 'Database' },
    { key: 'ollama',    label: 'LLM'      },
    { key: 'api',       label: 'API'      },
    { key: 'airflow',   label: 'Airflow'  },
    { key: 'sendgrid',  label: 'Email'    },
    { key: 'tavily',    label: 'Search'   },
    { key: 'slack',     label: 'Slack'    },
  ];

  const getStatusColor = (status) => {
    if (status === 'ok')      return 'bg-green-500';
    if (status === 'warning') return 'bg-yellow-500';
    return 'bg-red-500';
  };

  return (
    <div className="bg-white rounded-lg shadow p-4 mb-6">
      <h2 className="text-sm font-semibold text-gray-700 mb-3">Agent Health</h2>
      <div className="flex gap-6 flex-wrap">
        {services.map((svc) => {
          const statusObj = health?.[svc.key];
          const statusStr = typeof statusObj === 'object'
            ? (statusObj?.status || 'unknown')
            : (statusObj || 'unknown');
          return (
            <div key={svc.key} className="flex items-center gap-2">
              <div className={`w-3 h-3 rounded-full ${getStatusColor(statusStr)} ${isLoading ? 'animate-pulse' : ''}`} />
              <span className="text-xs text-gray-600">{svc.label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function PipelineStageCards({ pipelineData, isLoading }) {
  const stages = [
    { key: 'new',            label: 'New',       color: 'bg-gray-100 text-gray-800'    },
    { key: 'enriched',       label: 'Enriched',  color: 'bg-gray-100 text-gray-800'    },
    { key: 'scored',         label: 'Scored',    color: 'bg-purple-100 text-purple-800'},
    { key: 'approved',       label: 'Approved',  color: 'bg-purple-100 text-purple-800'},
    { key: 'contacted',      label: 'Contacted', color: 'bg-yellow-100 text-yellow-800'},
    { key: 'replied',        label: 'Replied',   color: 'bg-blue-100 text-blue-800'    },
    { key: 'meeting_booked', label: 'Meeting',   color: 'bg-blue-100 text-blue-800'    },
    { key: 'won',            label: 'Won',       color: 'bg-green-100 text-green-800'  },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-8 mb-6">
      {stages.map((stage) => {
        const count = pipelineData?.[stage.key] ?? 0;
        return (
          <div
            key={stage.key}
            className={`rounded-lg p-4 text-center ${stage.color} ${isLoading ? 'opacity-50' : ''}`}
          >
            <p className="text-xs font-semibold mb-1">{stage.label}</p>
            <p className="text-2xl font-bold">{count}</p>
          </div>
        );
      })}
    </div>
  );
}

function PipelineValueBanner({ pipelineData, isLoading }) {
  const pipelineValue = pipelineData?.pipeline_value_mid || 0;
  const revenueEstimate = pipelineValue * 0.24;

  return (
    <div className={`bg-gradient-to-r from-green-600 to-green-500 rounded-lg shadow p-6 mb-6 text-white ${isLoading ? 'opacity-70' : ''}`}>
      <div className="grid md:grid-cols-2 gap-4">
        <div>
          <p className="text-sm font-semibold opacity-90">Total Pipeline Value</p>
          <p className="text-3xl font-bold">{formatCurrency(pipelineValue)} estimated savings</p>
        </div>
        <div>
          <p className="text-sm font-semibold opacity-90">Troy &amp; Banks Revenue Estimate</p>
          <p className="text-3xl font-bold">{formatCurrency(revenueEstimate)}</p>
        </div>
      </div>
    </div>
  );
}

function HotLeadsBanner({ pipelineData, navigate }) {
  const hotLeadsCount = pipelineData?.replied || 0;
  if (!hotLeadsCount) return null;

  return (
    <div className="bg-red-600 rounded-lg shadow p-4 mb-6 text-white flex items-center justify-between">
      <p className="text-lg font-bold">
        🔥 {hotLeadsCount} HOT LEADS need your attention right now
      </p>
      <button
        onClick={() => navigate('/leads?status=replied')}
        className="px-4 py-2 bg-white text-red-600 font-semibold rounded-lg hover:bg-gray-100 transition"
      >
        Review Now
      </button>
    </div>
  );
}

/** Status-only: how many companies still need analyst scoring */
function AnalystStatusCard({ pipelineData, navigate }) {
  const pending = pipelineData?.pending_analyst ?? 0;

  return (
    <div className={`bg-white rounded-lg shadow p-5 mb-4 border-l-4 ${pending > 0 ? 'border-purple-500' : 'border-gray-200'}`}>
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-base font-bold text-gray-900">🧠 Analyst — Score Companies</h3>
          <p className="text-sm text-gray-500 mt-1">
            {pending > 0
              ? <><span className="text-purple-700 font-semibold">{pending} companies</span> waiting to be scored</>
              : <span className="text-green-600 font-medium">✓ All companies scored</span>
            }
          </p>
        </div>
        {pending > 0 && (
          <button
            onClick={() => navigate('/triggers')}
            className="ml-4 px-3 py-1.5 bg-purple-100 text-purple-700 font-semibold rounded-lg hover:bg-purple-200 transition text-sm whitespace-nowrap"
          >
            Go to Triggers →
          </button>
        )}
      </div>
    </div>
  );
}

/** Status-only: contact coverage progress bar */
function EnrichStatusCard({ pipelineData, navigate }) {
  const contactsWith   = pipelineData?.contacts_with   ?? 0;
  const contactsNeeded = pipelineData?.contacts_needed ?? 0;
  const total = contactsWith + contactsNeeded;
  const pct   = total > 0 ? Math.round((contactsWith / total) * 100) : 0;

  return (
    <div className={`bg-white rounded-lg shadow p-5 mb-4 border-l-4 ${contactsNeeded > 0 ? 'border-orange-400' : 'border-gray-200'}`}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <h3 className="text-base font-bold text-gray-900">👤 Contact Enrichment</h3>
          <p className="text-sm text-gray-500 mt-1">
            <span className="text-green-700 font-semibold">{contactsWith} companies</span> have a contact
            {' · '}
            {contactsNeeded > 0
              ? <span className="text-orange-600 font-semibold">{contactsNeeded} still need enrichment</span>
              : <span className="text-green-600 font-semibold">all enriched</span>
            }
          </p>
          {total > 0 && (
            <div className="mt-2">
              <div className="flex justify-between text-xs text-gray-500 mb-1">
                <span>Contact coverage</span>
                <span>{pct}% ({contactsWith}/{total})</span>
              </div>
              <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
                <div
                  className="h-2 bg-orange-500 rounded-full transition-all duration-500"
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          )}
        </div>
        {contactsNeeded > 0 && (
          <button
            onClick={() => navigate('/triggers')}
            className="mt-1 px-3 py-1.5 bg-orange-100 text-orange-700 font-semibold rounded-lg hover:bg-orange-200 transition text-sm whitespace-nowrap"
          >
            Go to Triggers →
          </button>
        )}
      </div>
    </div>
  );
}

/** Summary stats row: pending emails, approved leads, etc. */
function PipelineStatsSummary({ pipelineData, pendingEmailsCount, navigate }) {
  const stats = [
    {
      label: 'Pending Emails',
      value: pendingEmailsCount,
      color: pendingEmailsCount > 0 ? 'text-green-700' : 'text-gray-400',
      action: pendingEmailsCount > 0 ? () => navigate('/emails/review') : null,
      actionLabel: 'Review →',
    },
    {
      label: 'Approved Leads',
      value: pipelineData?.approved ?? 0,
      color: (pipelineData?.approved ?? 0) > 0 ? 'text-purple-700' : 'text-gray-400',
      action: null,
    },
    {
      label: 'Total Active',
      value: pipelineData?.total_active ?? 0,
      color: 'text-blue-700',
      action: () => navigate('/leads'),
      actionLabel: 'View All →',
    },
    {
      label: 'Won',
      value: pipelineData?.won ?? 0,
      color: (pipelineData?.won ?? 0) > 0 ? 'text-green-700' : 'text-gray-400',
      action: null,
    },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      {stats.map((s) => (
        <div key={s.label} className="bg-white rounded-lg shadow p-4 text-center">
          <p className="text-xs font-semibold text-gray-500 mb-1">{s.label}</p>
          <p className={`text-2xl font-bold ${s.color}`}>{s.value}</p>
          {s.action && (
            <button
              onClick={s.action}
              className="mt-1 text-xs text-blue-600 hover:underline"
            >
              {s.actionLabel}
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

function RecentActivityFeed({ activities, isLoading }) {
  return (
    <div className="bg-white rounded-lg shadow p-6">
      <h2 className="text-lg font-bold text-gray-900 mb-4">Recent Activity</h2>
      <div className="space-y-4">
        {isLoading ? (
          <p className="text-gray-500 text-center py-8">Loading activity...</p>
        ) : activities && activities.length > 0 ? (
          activities.map((activity, idx) => {
            const { icon, label, color } = getEventIcon(activity.event_type);
            return (
              <div key={idx} className="flex gap-4 pb-4 border-b last:border-b-0">
                <div className={`w-10 h-10 rounded-full ${color} flex items-center justify-center flex-shrink-0`}>
                  {icon}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="font-semibold text-gray-900 truncate">{activity.company_name}</p>
                  <p className="text-sm text-gray-600">{activity.description}</p>
                </div>
                <p className="text-xs text-gray-500 flex-shrink-0">
                  {formatTimeAgo(activity.timestamp)}
                </p>
              </div>
            );
          })
        ) : (
          <p className="text-gray-500 text-center py-8">No activity yet</p>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// MAIN COMPONENT
// ============================================================================

export default function Pipeline() {
  const navigate = useNavigate();
  const [pipelineData,      setPipelineData]      = useState(null);
  const [healthData,        setHealthData]        = useState(null);
  const [activities,        setActivities]        = useState([]);
  const [pendingEmailsCount,setPendingEmailsCount] = useState(0);
  const [lastUpdated,       setLastUpdated]       = useState(null);
  const [isLoading,         setIsLoading]         = useState(true);
  const [error,             setError]             = useState(null);

  const loadAllData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [pipelineRes, healthRes, activitiesRes, emailsRes] = await Promise.all([
        fetchPipelineStatus(),
        fetchAgentHealth(),
        fetchRecentActivity(10),
        fetchPendingEmails(),
      ]);
      setPipelineData(pipelineRes);
      setHealthData(healthRes);
      setActivities(activitiesRes?.activities || []);
      setPendingEmailsCount(emailsRes?.total_count || 0);
      setLastUpdated(new Date());
    } catch (err) {
      console.error('Failed to load pipeline data:', err);
      setError('Failed to load pipeline data. Check API connection.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => { loadAllData(); }, []);

  // Auto-refresh health every 60s
  useEffect(() => {
    const id = setInterval(async () => {
      try { setHealthData(await fetchAgentHealth()); } catch {}
    }, 60_000);
    return () => clearInterval(id);
  }, []);

  // Auto-refresh activity every 30s
  useEffect(() => {
    const id = setInterval(async () => {
      try {
        const res = await fetchRecentActivity(10);
        setActivities(res?.activities || []);
      } catch {}
    }, 30_000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="h-full overflow-y-auto bg-gray-50 p-6">
      {isLoading && <LoadingOverlay message="Loading pipeline data..." />}
      <div className="max-w-7xl mx-auto">

        <PageHeader onRefresh={loadAllData} isLoading={isLoading} lastUpdated={lastUpdated} />

        {error && (
          <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded-lg mb-6">
            {error}
          </div>
        )}

        <AgentHealthBar health={healthData} isLoading={isLoading} />

        <PipelineStageCards pipelineData={pipelineData} isLoading={isLoading} />

        <PipelineValueBanner pipelineData={pipelineData} isLoading={isLoading} />

        <HotLeadsBanner pipelineData={pipelineData} navigate={navigate} />

        {/* Key stats summary */}
        <PipelineStatsSummary
          pipelineData={pipelineData}
          pendingEmailsCount={pendingEmailsCount}
          navigate={navigate}
        />

        {/* Status-only cards — link to Triggers for action */}
        <AnalystStatusCard pipelineData={pipelineData} navigate={navigate} />
        <EnrichStatusCard  pipelineData={pipelineData} navigate={navigate} />

        <RecentActivityFeed activities={activities} isLoading={isLoading} />

      </div>
    </div>
  );
}
