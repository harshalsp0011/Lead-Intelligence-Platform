/**
 * Pipeline Overview Page
 * 
 * This is the home page of the dashboard showing the full pipeline at a glance.
 * Displays agent health, pipeline stages, lead counts, activity feed, and quick actions.
 * 
 * Components:
 * - PageHeader: Title, subtitle, last updated timestamp, refresh button
 * - AgentHealthBar: Colored status indicators for services (auto-refreshes 60s)
 * - PipelineStageCards: Lead counts by stage with color coding
 * - PipelineValueBanner: Total pipeline value and revenue estimates
 * - HotLeadsBanner: Alert for replied leads needing attention
 * - QuickActionButtons: Quick trigger actions
 * - RecentActivityFeed: Last 10 pipeline events (auto-refreshes 30s)
 * - TriggerModal: Modal for triggering full pipeline
 * 
 * Usage:
 *   import Pipeline from './pages/Pipeline';
 *   <Pipeline />
 */

import React, { useState, useEffect, useMemo } from 'react';
import LoadingOverlay from '../components/LoadingOverlay';
import { useNavigate } from 'react-router-dom';
import {
  fetchPipelineStatus,
  fetchAgentHealth,
  fetchRecentActivity,
  fetchPendingEmails,
  triggerScout,
  triggerFullPipeline,
} from '../services/api';

// ============================================================================
// UTILITIES
// ============================================================================

/**
 * Format timestamp to relative time ("2 hours ago")
 */
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

/**
 * Get event icon and color by event type
 */
function getEventIcon(eventType) {
  const icons = {
    company_found: { icon: '🔍', label: 'Found', color: 'bg-gray-100' },
    scored_high: { icon: '⭐', label: 'Scored', color: 'bg-green-100' },
    email_sent: { icon: '✉️', label: 'Sent', color: 'bg-blue-100' },
    email_opened: { icon: '👁️', label: 'Opened', color: 'bg-yellow-100' },
    reply_received: { icon: '💬', label: 'Reply', color: 'bg-red-100' },
  };
  return icons[eventType] || { icon: '•', label: 'Event', color: 'bg-gray-100' };
}

/**
 * Format currency for pipeline value
 */
function formatCurrency(value) {
  if (!value) return '$0';
  if (value >= 1000000) return `$${(value / 1000000).toFixed(1)}M`;
  if (value >= 1000) return `$${(value / 1000).toFixed(0)}k`;
  return `$${value}`;
}

// ============================================================================
// SUB-COMPONENTS
// ============================================================================

/**
 * PageHeader: Title, subtitle, timestamp, refresh button
 */
function PageHeader({ onRefresh, isLoading, lastUpdated }) {
  return (
    <div className="flex justify-between items-start mb-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Pipeline Overview</h1>
        <p className="text-gray-600 mt-1">Live lead generation status for Troy & Banks</p>
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

/**
 * AgentHealthBar: Colored status dots for services
 */
function AgentHealthBar({ health, isLoading }) {
  // Keys must match what /pipeline/health returns: postgres, ollama, api, airflow, sendgrid, tavily, slack
  const services = [
    { key: 'postgres',  label: 'Database' },
    { key: 'ollama',    label: 'LLM' },
    { key: 'api',       label: 'API' },
    { key: 'airflow',   label: 'Airflow' },
    { key: 'sendgrid',  label: 'Email' },
    { key: 'tavily',    label: 'Search' },
    { key: 'slack',     label: 'Slack' },
  ];

  const getStatusColor = (status) => {
    if (status === 'ok') return 'bg-green-500';
    if (status === 'warning') return 'bg-yellow-500';
    return 'bg-red-500';
  };

  return (
    <div className="bg-white rounded-lg shadow p-4 mb-6">
      <h2 className="text-sm font-semibold text-gray-700 mb-3">Agent Health</h2>
      <div className="flex gap-6">
        {services.map((svc) => {
          const statusObj = health?.[svc.key];
          const statusStr = typeof statusObj === 'object' ? (statusObj?.status || 'unknown') : (statusObj || 'unknown');
          return (
            <div key={svc.key} className="flex items-center gap-2">
              <div
                className={`w-3 h-3 rounded-full ${getStatusColor(statusStr)} ${
                  isLoading ? 'animate-pulse' : ''
                }`}
              />
              <span className="text-xs text-gray-600">{svc.label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * PipelineStageCards: Cards showing lead counts by stage
 */
function PipelineStageCards({ pipelineData, isLoading }) {
  // API returns keys without _count suffix: { new: 59, scored: 0, ... }
  // meeting_booked is the API key for the meeting stage
  const stages = [
    { key: 'new', label: 'New', color: 'bg-gray-100 text-gray-800' },
    { key: 'enriched', label: 'Enriched', color: 'bg-gray-100 text-gray-800' },
    { key: 'scored', label: 'Scored', color: 'bg-purple-100 text-purple-800' },
    { key: 'approved', label: 'Approved', color: 'bg-purple-100 text-purple-800' },
    { key: 'contacted', label: 'Contacted', color: 'bg-yellow-100 text-yellow-800' },
    { key: 'replied', label: 'Replied', color: 'bg-blue-100 text-blue-800' },
    { key: 'meeting_booked', label: 'Meeting', color: 'bg-blue-100 text-blue-800' },
    { key: 'won', label: 'Won', color: 'bg-green-100 text-green-800' },
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

/**
 * PipelineValueBanner: Shows pipeline value and revenue estimates
 */
function PipelineValueBanner({ pipelineData, isLoading }) {
  const pipelineValue = pipelineData?.pipeline_value_mid || 0;
  const revenueEstimate = pipelineValue * 0.24;  // 24% contingency fee estimate

  return (
    <div
      className={`bg-gradient-to-r from-green-600 to-green-500 rounded-lg shadow p-6 mb-6 text-white ${
        isLoading ? 'opacity-70' : ''
      }`}
    >
      <div className="grid md:grid-cols-2 gap-4">
        <div>
          <p className="text-sm font-semibold opacity-90">Total Pipeline Value</p>
          <p className="text-3xl font-bold">{formatCurrency(pipelineValue)} estimated savings</p>
        </div>
        <div>
          <p className="text-sm font-semibold opacity-90">Troy & Banks Revenue Estimate</p>
          <p className="text-3xl font-bold">{formatCurrency(revenueEstimate)}</p>
        </div>
      </div>
    </div>
  );
}

/**
 * HotLeadsBanner: Alert for replied leads needing attention
 */
function HotLeadsBanner({ pipelineData, navigate }) {
  const hotLeadsCount = pipelineData?.replied || 0;
  const hasUnalerledLeads = hotLeadsCount > 0; // Assume all replied leads aren't alerted

  if (!hasUnalerledLeads) return null;

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

/**
 * QuickActionButtons: Quick trigger actions
 */
function QuickActionButtons({
  onRunScout,
  onRunFull,
  pendingEmailsCount,
  navigate,
  isLoadingScout,
  showTriggerModal,
}) {
  return (
    <div className="grid md:grid-cols-3 gap-4 mb-6">
      <button
        onClick={onRunScout}
        disabled={isLoadingScout}
        className="px-4 py-3 bg-blue-600 text-white font-semibold rounded-lg hover:bg-blue-700 disabled:bg-gray-400 transition flex items-center justify-center gap-2"
      >
        {isLoadingScout ? '⏳ Running...' : '🔍 Run Scout — Buffalo Healthcare'}
      </button>
      <button
        onClick={showTriggerModal}
        className="px-4 py-3 bg-purple-600 text-white font-semibold rounded-lg hover:bg-purple-700 transition"
      >
        ▶️ Run Full Pipeline
      </button>
      <button
        onClick={() => navigate('/emails/review')}
        className="px-4 py-3 bg-green-600 text-white font-semibold rounded-lg hover:bg-green-700 transition"
      >
        ✉️ Review Pending Emails ({pendingEmailsCount})
      </button>
    </div>
  );
}

/**
 * RecentActivityFeed: Last 10 pipeline events with auto-refresh
 */
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

/**
 * TriggerModal: Modal for triggering full pipeline with form
 */
function TriggerModal({ isOpen, onClose, onSubmit, isSubmitting }) {
  const [formData, setFormData] = useState({
    industry: 'healthcare',
    location: 'Buffalo, NY',
    count: 20,
    run_mode: 'full',
  });

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => ({
      ...prev,
      [name]: name === 'count' ? parseInt(value, 10) : value,
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    await onSubmit(formData);
    setFormData({
      industry: 'healthcare',
      location: 'Buffalo, NY',
      count: 20,
      run_mode: 'full',
    });
    onClose();
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-lg p-6 w-96 max-h-[90vh] overflow-auto">
        <h2 className="text-xl font-bold text-gray-900 mb-4">Trigger Full Pipeline</h2>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Industry Dropdown */}
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-2">Industry</label>
            <select
              name="industry"
              value={formData.industry}
              onChange={handleChange}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="healthcare">Healthcare</option>
              <option value="hospitality">Hospitality</option>
              <option value="manufacturing">Manufacturing</option>
              <option value="retail">Retail</option>
              <option value="public_sector">Public Sector</option>
              <option value="office">Office</option>
            </select>
          </div>

          {/* Location Input */}
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-2">Location</label>
            <input
              type="text"
              name="location"
              value={formData.location}
              onChange={handleChange}
              placeholder="Buffalo, NY"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          {/* Count Slider */}
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-2">
              Count: {formData.count}
            </label>
            <input
              type="range"
              name="count"
              min="5"
              max="100"
              value={formData.count}
              onChange={handleChange}
              className="w-full"
            />
            <div className="flex justify-between text-xs text-gray-500 mt-1">
              <span>5</span>
              <span>100</span>
            </div>
          </div>

          {/* Run Mode Radio Buttons */}
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-2">Run Mode</label>
            <div className="space-y-2">
              {[
                { value: 'full', label: 'Full Pipeline' },
                { value: 'scout_only', label: 'Scout Only' },
                { value: 'analyst_only', label: 'Analyst Only' },
                { value: 'writer_only', label: 'Writer Only' },
              ].map((mode) => (
                <label key={mode.value} className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="run_mode"
                    value={mode.value}
                    checked={formData.run_mode === mode.value}
                    onChange={handleChange}
                    className="w-4 h-4"
                  />
                  <span className="text-sm text-gray-700">{mode.label}</span>
                </label>
              ))}
            </div>
          </div>

          {/* Buttons */}
          <div className="flex gap-3 mt-6">
            <button
              type="submit"
              disabled={isSubmitting}
              className="flex-1 px-4 py-2 bg-blue-600 text-white font-semibold rounded-lg hover:bg-blue-700 disabled:bg-gray-400 transition"
            >
              {isSubmitting ? 'Running...' : 'Run Now'}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2 bg-gray-200 text-gray-800 font-semibold rounded-lg hover:bg-gray-300 transition"
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ============================================================================
// MAIN COMPONENT
// ============================================================================

/**
 * Pipeline: Home page showing full pipeline overview
 */
export default function Pipeline() {
  const navigate = useNavigate();
  const [pipelineData, setPipelineData] = useState(null);
  const [healthData, setHealthData] = useState(null);
  const [activities, setActivities] = useState([]);
  const [pendingEmailsCount, setPendingEmailsCount] = useState(0);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingScout, setIsLoadingScout] = useState(false);
  const [isSubmittingModal, setIsSubmittingModal] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [error, setError] = useState(null);

  /**
   * Fetch all data
   */
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

  /**
   * Load data on mount
   */
  useEffect(() => {
    loadAllData();
  }, []);

  /**
   * Auto-refresh health every 60 seconds
   */
  useEffect(() => {
    const healthInterval = setInterval(async () => {
      try {
        const healthRes = await fetchAgentHealth();
        setHealthData(healthRes);
      } catch (err) {
        console.error('Failed to refresh health:', err);
      }
    }, 60000);
    return () => clearInterval(healthInterval);
  }, []);

  /**
   * Auto-refresh activity every 30 seconds
   */
  useEffect(() => {
    const activityInterval = setInterval(async () => {
      try {
        const activitiesRes = await fetchRecentActivity(10);
        setActivities(activitiesRes?.activities || []);
      } catch (err) {
        console.error('Failed to refresh activity:', err);
      }
    }, 30000);
    return () => clearInterval(activityInterval);
  }, []);

  /**
   * Run scout trigger
   */
  const handleRunScout = async () => {
    setIsLoadingScout(true);
    try {
      await triggerScout('healthcare', 'Buffalo, NY', 20);
      // Show success toast (implement with toast library in real app)
      setTimeout(() => loadAllData(), 1000);
    } catch (err) {
      console.error('Scout trigger failed:', err);
      setError('Failed to trigger scout. Try again.');
    } finally {
      setIsLoadingScout(false);
    }
  };

  /**
   * Submit full pipeline trigger
   */
  const handleTriggerSubmit = async (formData) => {
    setIsSubmittingModal(true);
    try {
      await triggerFullPipeline(formData.industry, formData.location, formData.count);
      // Show success toast
      setTimeout(() => loadAllData(), 1000);
    } catch (err) {
      console.error('Pipeline trigger failed:', err);
      setError('Failed to trigger pipeline. Try again.');
    } finally {
      setIsSubmittingModal(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto bg-gray-50 p-6">
      {isLoading && <LoadingOverlay message="Loading pipeline data..." />}
      <div className="max-w-7xl mx-auto">
        {/* Page Header */}
        <PageHeader onRefresh={loadAllData} isLoading={isLoading} lastUpdated={lastUpdated} />

        {/* Error Alert */}
        {error && (
          <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded-lg mb-6">
            {error}
          </div>
        )}

        {/* Agent Health Bar */}
        <AgentHealthBar health={healthData} isLoading={isLoading} />

        {/* Pipeline Stage Cards */}
        <PipelineStageCards pipelineData={pipelineData} isLoading={isLoading} />

        {/* Pipeline Value Banner */}
        <PipelineValueBanner pipelineData={pipelineData} isLoading={isLoading} />

        {/* Hot Leads Banner */}
        <HotLeadsBanner pipelineData={pipelineData} navigate={navigate} />

        {/* Quick Action Buttons */}
        <QuickActionButtons
          onRunScout={handleRunScout}
          onRunFull={() => setShowModal(true)}
          pendingEmailsCount={pendingEmailsCount}
          navigate={navigate}
          isLoadingScout={isLoadingScout}
          showTriggerModal={() => setShowModal(true)}
        />

        {/* Recent Activity Feed */}
        <RecentActivityFeed activities={activities} isLoading={isLoading} />
      </div>

      {/* Trigger Modal */}
      <TriggerModal
        isOpen={showModal}
        onClose={() => setShowModal(false)}
        onSubmit={handleTriggerSubmit}
        isSubmitting={isSubmittingModal}
      />
    </div>
  );
}
