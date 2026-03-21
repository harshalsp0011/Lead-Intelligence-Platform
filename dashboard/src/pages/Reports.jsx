/**
 * Reports & Analytics Page
 * 
 * Displays weekly performance metrics, lead funnel, industry breakdown,
 * top leads, and reply sentiment analysis.
 * Supports date range filtering and real-time refresh.
 * 
 * Route: /reports
 * 
 * Components:
 * - PageHeader: Title, date range picker, refresh button
 * - SummaryMetricCards: 6 key metrics (found, high, sent, open, reply, value)
 * - LeadFunnelChart: Horizontal funnel chart (Recharts)
 * - IndustryBreakdownTable: Leads by industry with conversion % 
 * - TopLeadsThisWeek: Top 10 leads by score (clickable)
 * - ReplyBreakdownChart: Pie chart of reply sentiment (Recharts)
 * 
 * Usage:
 *   import Reports from './pages/Reports';
 *   <Route path="/reports" element={<Reports />} />
 */

import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import LoadingOverlay from '../components/LoadingOverlay';
import {
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import {
  fetchWeeklyReport,
  fetchTopLeads,
} from '../services/api';

// ============================================================================
// UTILITIES
// ============================================================================

/**
 * Get date N days ago
 */
function getDateNDaysAgo(days) {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return date.toISOString().split('T')[0];
}

/**
 * Format date for input
 */
function formatDateForInput(dateString) {
  return dateString || new Date().toISOString().split('T')[0];
}

/**
 * Format currency
 */
function formatCurrency(value) {
  if (!value) return '$0';
  if (value >= 1000000) return `$${(value / 1000000).toFixed(1)}M`;
  if (value >= 1000) return `$${(value / 1000).toFixed(0)}k`;
  return `$${value}`;
}

/**
 * Calculate percentage
 */
function calculatePercentage(numerator, denominator) {
  if (!denominator || denominator === 0) return 0;
  return ((numerator / denominator) * 100).toFixed(1);
}

// ============================================================================
// SUB-COMPONENTS
// ============================================================================

/**
 * PageHeader: Title, date range picker, refresh button
 */
function PageHeader({ startDate, endDate, onDateChange, onRefresh, isLoading }) {
  return (
    <div className="flex justify-between items-start mb-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Reports & Analytics</h1>
        <p className="text-gray-600 mt-1">Weekly performance metrics</p>
      </div>

      <div className="flex gap-4 items-end">
        <div>
          <label className="block text-xs font-semibold text-gray-700 mb-1">Start Date</label>
          <input
            type="date"
            value={startDate}
            onChange={(e) => onDateChange(e.target.value, endDate)}
            className="px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div>
          <label className="block text-xs font-semibold text-gray-700 mb-1">End Date</label>
          <input
            type="date"
            value={endDate}
            onChange={(e) => onDateChange(startDate, e.target.value)}
            className="px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <button
          onClick={onRefresh}
          disabled={isLoading}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400 transition font-semibold"
        >
          {isLoading ? '⏳ Refreshing...' : '🔄 Refresh'}
        </button>
      </div>
    </div>
  );
}

/**
 * SummaryMetricCards: 6 key metrics
 */
function SummaryMetricCards({ report, isLoading }) {
  const cards = [
    {
      title: 'Companies Found',
      value: report?.companies_found || 0,
      sub: 'this week',
      color: 'bg-blue-50 text-blue-700',
      icon: '🔍',
    },
    {
      title: 'High Score Leads',
      value: report?.leads_high || 0,
      sub: 'qualified prospects',
      color: 'bg-green-50 text-green-700',
      icon: '⭐',
    },
    {
      title: 'Emails Sent',
      value: report?.emails_sent || 0,
      sub: 'outreach sent',
      color: 'bg-orange-50 text-orange-700',
      icon: '✉️',
    },
    {
      title: 'Open Rate',
      value: `${report?.open_rate_pct || 0}%`,
      sub: 'industry avg is 20%',
      color: 'bg-yellow-50 text-yellow-700',
      icon: '👁️',
    },
    {
      title: 'Reply Rate',
      value: `${report?.reply_rate_pct || 0}%`,
      sub: 'industry avg is 3%',
      color: 'bg-purple-50 text-purple-700',
      icon: '💬',
    },
    {
      title: 'Pipeline Value',
      value: formatCurrency(report?.pipeline_value_estimated),
      sub: 'estimated savings',
      color: 'bg-green-50 text-green-700',
      icon: '💰',
    },
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
      {cards.map((card, idx) => (
        <div
          key={idx}
          className={`rounded-lg p-4 ${card.color} ${isLoading ? 'opacity-50' : ''}`}
        >
          <p className="text-sm font-semibold mb-2">{card.icon} {card.title}</p>
          <p className="text-2xl font-bold">{card.value}</p>
          <p className="text-xs mt-1 opacity-75">{card.sub}</p>
        </div>
      ))}
    </div>
  );
}

/**
 * LeadFunnelChart: Horizontal funnel
 */
function LeadFunnelChart({ report, isLoading }) {
  if (isLoading || !report) {
    return (
      <div className="bg-white rounded-lg shadow p-6 mb-6 h-80 flex items-center justify-center">
        <p className="text-gray-500">Loading chart...</p>
      </div>
    );
  }

  const funnelData = [
    { stage: 'Found', count: report.companies_found || 0 },
    { stage: 'Scored High', count: report.leads_high || 0 },
    { stage: 'Contacted', count: report.emails_sent || 0 },
    { stage: 'Opened', count: Math.round(((report.open_rate_pct || 0) / 100) * (report.emails_sent || 0)) },
    { stage: 'Replied', count: Math.round(((report.reply_rate_pct || 0) / 100) * (report.emails_sent || 0)) },
    { stage: 'Meeting', count: report.meetings_scheduled || 0 },
  ];

  const maxCount = Math.max(...funnelData.map(d => d.count), 1);

  return (
    <div className="bg-white rounded-lg shadow p-6 mb-6">
      <h2 className="text-lg font-bold text-gray-900 mb-4">Lead Funnel</h2>
      <div className="space-y-4">
        {funnelData.map((item, idx) => {
          const prevCount = idx === 0 ? item.count : funnelData[idx - 1].count;
          const dropoff = prevCount > 0 ? (((prevCount - item.count) / prevCount) * 100).toFixed(0) : 0;
          const width = (item.count / maxCount) * 100;

          return (
            <div key={item.stage}>
              <div className="flex justify-between items-center mb-1">
                <span className="text-sm font-semibold text-gray-700">{item.stage}</span>
                <span className="text-xs text-gray-600">
                  {item.count} {idx > 0 && `(-${dropoff}%)`}
                </span>
              </div>
              <div className="w-full bg-gray-200 rounded-full h-6">
                <div
                  className="bg-blue-600 h-6 rounded-full flex items-center justify-end pr-2"
                  style={{ width: `${width}%` }}
                >
                  {width > 15 && (
                    <span className="text-xs font-bold text-white">{item.count}</span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * IndustryBreakdownTable: Leads by industry
 */
function IndustryBreakdownTable({ report, isLoading }) {
  if (isLoading || !report?.by_industry) {
    return (
      <div className="bg-white rounded-lg shadow p-6 mb-6">
        <h2 className="text-lg font-bold text-gray-900 mb-4">Industry Breakdown</h2>
        <p className="text-gray-500">Loading...</p>
      </div>
    );
  }

  const tableData = (report.by_industry || [])
    .map((ind) => ({
      ...ind,
      conversionPct: calculatePercentage(ind.replied, ind.found || 1),
    }))
    .sort((a, b) => parseFloat(b.conversionPct) - parseFloat(a.conversionPct));

  return (
    <div className="bg-white rounded-lg shadow p-6 mb-6">
      <h2 className="text-lg font-bold text-gray-900 mb-4">Industry Breakdown</h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-100 border-b">
            <tr>
              <th className="px-4 py-2 text-left font-semibold text-gray-700">Industry</th>
              <th className="px-4 py-2 text-left font-semibold text-gray-700">Found</th>
              <th className="px-4 py-2 text-left font-semibold text-gray-700">Scored High</th>
              <th className="px-4 py-2 text-left font-semibold text-gray-700">Contacted</th>
              <th className="px-4 py-2 text-left font-semibold text-gray-700">Replied</th>
              <th className="px-4 py-2 text-left font-semibold text-gray-700">Conversion %</th>
            </tr>
          </thead>
          <tbody>
            {tableData.map((row, idx) => (
              <tr key={idx} className="border-b hover:bg-gray-50">
                <td className="px-4 py-2 font-semibold text-gray-900">{row.industry}</td>
                <td className="px-4 py-2 text-gray-700">{row.found}</td>
                <td className="px-4 py-2 text-gray-700">{row.high_score}</td>
                <td className="px-4 py-2 text-gray-700">{row.contacted}</td>
                <td className="px-4 py-2 text-gray-700">{row.replied}</td>
                <td className="px-4 py-2">
                  <span className="px-2 py-1 bg-green-100 text-green-800 rounded text-xs font-bold">
                    {row.conversionPct}%
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/**
 * TopLeadsThisWeek: Top 10 leads by score
 */
function TopLeadsThisWeek({ topLeads, isLoading, navigate }) {
  if (isLoading || !topLeads) {
    return (
      <div className="bg-white rounded-lg shadow p-6 mb-6">
        <h2 className="text-lg font-bold text-gray-900 mb-4">Top Leads This Week</h2>
        <p className="text-gray-500">Loading...</p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg shadow p-6 mb-6">
      <h2 className="text-lg font-bold text-gray-900 mb-4">Top Leads This Week</h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-100 border-b">
            <tr>
              <th className="px-4 py-2 text-left font-semibold text-gray-700">Company</th>
              <th className="px-4 py-2 text-left font-semibold text-gray-700">Industry</th>
              <th className="px-4 py-2 text-left font-semibold text-gray-700">Score</th>
              <th className="px-4 py-2 text-left font-semibold text-gray-700">Est. Savings</th>
              <th className="px-4 py-2 text-left font-semibold text-gray-700">Status</th>
              <th className="px-4 py-2 text-left font-semibold text-gray-700">Contact</th>
            </tr>
          </thead>
          <tbody>
            {topLeads.map((lead, idx) => (
              <tr key={idx} className="border-b hover:bg-gray-50">
                <td className="px-4 py-2">
                  <button
                    onClick={() => navigate(`/leads/${lead.id}`)}
                    className="font-semibold text-blue-600 hover:underline"
                  >
                    {lead.company_name}
                  </button>
                </td>
                <td className="px-4 py-2 text-gray-700">{lead.industry}</td>
                <td className="px-4 py-2">
                  <span className="font-bold text-blue-600">{lead.lead_score}/100</span>
                </td>
                <td className="px-4 py-2 text-gray-700">
                  {formatCurrency(lead.savings_estimate_mid)}
                </td>
                <td className="px-4 py-2">
                  <span className="px-2 py-1 bg-blue-100 text-blue-800 rounded text-xs font-semibold">
                    {lead.status}
                  </span>
                </td>
                <td className="px-4 py-2 text-center">
                  {lead.contact_found ? '✓' : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/**
 * ReplyBreakdownChart: Pie chart of reply sentiment
 */
function ReplyBreakdownChart({ report, isLoading }) {
  if (isLoading || !report) {
    return (
      <div className="bg-white rounded-lg shadow p-6 mb-6 h-80 flex items-center justify-center">
        <p className="text-gray-500">Loading chart...</p>
      </div>
    );
  }

  const replyData = [
    {
      name: 'Positive',
      value: report.replies_positive || 0,
      fill: '#10b981',
    },
    {
      name: 'Neutral',
      value: report.replies_neutral || 0,
      fill: '#6366f1',
    },
    {
      name: 'Negative',
      value: report.replies_negative || 0,
      fill: '#ef4444',
    },
    {
      name: 'No Reply',
      value: (report.emails_sent || 0) - (report.replies_positive || 0) - (report.replies_neutral || 0) - (report.replies_negative || 0),
      fill: '#d1d5db',
    },
  ].filter(item => item.value > 0);

  if (replyData.length === 0) {
    return (
      <div className="bg-white rounded-lg shadow p-6 mb-6 h-80 flex items-center justify-center">
        <p className="text-gray-500">No reply data available</p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg shadow p-6 mb-6">
      <h2 className="text-lg font-bold text-gray-900 mb-4">Reply Sentiment Breakdown</h2>
      <ResponsiveContainer width="100%" height={300}>
        <PieChart>
          <Pie
            data={replyData}
            cx="50%"
            cy="50%"
            labelLine={false}
            label={({ name, value }) => `${name}: ${value}`}
            outerRadius={80}
            fill="#8884d8"
            dataKey="value"
          >
            {replyData.map((entry, index) => (
              <Cell key={`cell-${index}`} fill={entry.fill} />
            ))}
          </Pie>
          <Tooltip />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}

// ============================================================================
// MAIN COMPONENT
// ============================================================================

/**
 * Reports: Analytics and metrics page
 */
export default function Reports() {
  const navigate = useNavigate();

  const [startDate, setStartDate] = useState(getDateNDaysAgo(7));
  const [endDate, setEndDate] = useState(new Date().toISOString().split('T')[0]);
  const [report, setReport] = useState(null);
  const [topLeads, setTopLeads] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  /**
   * Load report data
   */
  const loadReport = async (start, end) => {
    setIsLoading(true);
    setError(null);
    try {
      const [reportData, topLeadsData] = await Promise.all([
        fetchWeeklyReport(start, end),
        fetchTopLeads(10),
      ]);

      setReport(reportData);
      setTopLeads(topLeadsData?.data || []);
    } catch (err) {
      console.error('Failed to load report:', err);
      setError('Failed to load report data. Check API connection.');
    } finally {
      setIsLoading(false);
    }
  };

  /**
   * Load on mount
   */
  useEffect(() => {
    loadReport(startDate, endDate);
  }, []);

  /**
   * Handle date change
   */
  const handleDateChange = (newStart, newEnd) => {
    setStartDate(newStart);
    setEndDate(newEnd);
    loadReport(newStart, newEnd);
  };

  /**
   * Handle refresh
   */
  const handleRefresh = () => {
    loadReport(startDate, endDate);
  };

  return (
    <div className="h-full overflow-y-auto bg-gray-50 p-6">
      {isLoading && <LoadingOverlay message="Loading reports..." />}
      <div className="max-w-7xl mx-auto">
        <PageHeader
          startDate={startDate}
          endDate={endDate}
          onDateChange={handleDateChange}
          onRefresh={handleRefresh}
          isLoading={isLoading}
        />

        {error && (
          <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded-lg mb-6">
            {error}
          </div>
        )}

        <SummaryMetricCards report={report} isLoading={isLoading} />

        <LeadFunnelChart report={report} isLoading={isLoading} />

        <IndustryBreakdownTable report={report} isLoading={isLoading} />

        <TopLeadsThisWeek topLeads={topLeads} isLoading={isLoading} navigate={navigate} />

        <ReplyBreakdownChart report={report} isLoading={isLoading} />
      </div>
    </div>
  );
}
