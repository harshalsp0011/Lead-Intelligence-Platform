/**
 * Leads Page
 * 
 * Displays all leads in a filterable, sortable table with bulk actions.
 * Allows filtering by industry, state, tier, status, and score.
 * Supports pagination, CSV export, and inline lead actions.
 * 
 * Components:
 * - PageHeader: Title and CSV export button
 * - FilterBar: Industry, state, tier, status, min score, search filters
 * - LeadCountSummary: Shows total count and tier breakdown
 * - LeadsTable: Sortable table with pagination and row actions
 * - BulkApproveBar: Appears when leads are selected for bulk approval
 * 
 * Usage:
 *   import Leads from './pages/Leads';
 *   <Leads />
 */

import React, { useState, useEffect } from 'react';
import LoadingOverlay from '../components/LoadingOverlay';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  fetchLeads,
  fetchIndustries,
  approveLead,
  rejectLead,
} from '../services/api';

// ============================================================================
// UTILITIES
// ============================================================================

/**
 * Get badge color by tier
 */
function getTierColor(tier) {
  if (tier === 'high') return 'bg-green-100 text-green-800';
  if (tier === 'medium') return 'bg-yellow-100 text-yellow-800';
  return 'bg-gray-100 text-gray-800';
}

/**
 * Get badge color by status
 */
function getStatusColor(status) {
  const colors = {
    new: 'bg-gray-100 text-gray-800',
    scored: 'bg-purple-100 text-purple-800',
    approved: 'bg-blue-100 text-blue-800',
    contacted: 'bg-yellow-100 text-yellow-800',
    replied: 'bg-red-100 text-red-800',
    won: 'bg-green-100 text-green-800',
    lost: 'bg-gray-100 text-gray-800',
  };
  return colors[status] || 'bg-gray-100 text-gray-800';
}

/**
 * Format currency
 */
function formatCurrency(value) {
  if (!value) return '—';
  if (value >= 1000000) return `$${(value / 1000000).toFixed(1)}M`;
  if (value >= 1000) return `$${(value / 1000).toFixed(0)}k`;
  return `$${value}`;
}

/**
 * Export table data as CSV
 */
function exportTableAsCSV(leads, filename = 'leads.csv') {
  if (!leads || leads.length === 0) {
    console.warn('No data to export');
    return;
  }

  const headers = [
    'Company Name',
    'Industry',
    'State',
    'Sites',
    'Annual Spend',
    'Est. Savings',
    'Score',
    'Tier',
    'Status',
    'Contact Found',
  ];

  const rows = leads.map((lead) => [
    lead.company_name || '',
    lead.industry || '',
    lead.state || '',
    lead.estimated_sites || '',
    lead.estimated_annual_spend || '',
    lead.estimated_savings_range || '',
    lead.lead_score || '',
    lead.tier || '',
    lead.status || '',
    lead.contact_found ? 'Yes' : 'No',
  ]);

  const csvContent = [
    headers.join(','),
    ...rows.map((row) => row.map((cell) => `"${cell}"`).join(',')),
  ].join('\n');

  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
}

// ============================================================================
// SUB-COMPONENTS
// ============================================================================

/**
 * PageHeader: Title and CSV export button
 */
function PageHeader({ onExport, hasData }) {
  return (
    <div className="flex justify-between items-start mb-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Lead Intelligence</h1>
        <p className="text-gray-600 mt-1">All discovered and scored companies</p>
      </div>
      <button
        onClick={onExport}
        disabled={!hasData}
        className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:bg-gray-400 transition"
      >
        📥 Export CSV
      </button>
    </div>
  );
}

/**
 * FilterBar: Filter controls
 */
function FilterBar({ filters, onFilterChange, onApply, onClear, isLoading, industries }) {

  const tiers = [
    { value: '', label: 'All Tiers' },
    { value: 'high', label: 'High' },
    { value: 'medium', label: 'Medium' },
    { value: 'low', label: 'Low' },
  ];

  const statuses = [
    { value: '', label: 'All Statuses' },
    { value: 'new', label: 'New' },
    { value: 'scored', label: 'Scored' },
    { value: 'approved', label: 'Approved' },
    { value: 'contacted', label: 'Contacted' },
    { value: 'replied', label: 'Replied' },
    { value: 'won', label: 'Won' },
    { value: 'lost', label: 'Lost' },
  ];

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    onFilterChange({
      ...filters,
      [name]: name === 'min_score' ? parseInt(value, 10) || 0 : value,
      page: 1, // Reset to page 1 on filter change
    });
  };

  return (
    <div className="bg-white rounded-lg shadow p-4 mb-6">
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3 mb-3">
        {/* Industry — dynamic from DB */}
        <select
          name="industry"
          value={filters.industry || ''}
          onChange={handleInputChange}
          className="px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
        >
          <option value="">All Industries</option>
          {industries.map((ind) => (
            <option key={ind} value={ind}>
              {ind.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
            </option>
          ))}
        </select>

        {/* State */}
        <input
          type="text"
          name="state"
          value={filters.state || ''}
          onChange={handleInputChange}
          placeholder="State"
          className="px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
        />

        {/* Tier */}
        <select
          name="tier"
          value={filters.tier || ''}
          onChange={handleInputChange}
          className="px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
        >
          {tiers.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>

        {/* Status */}
        <select
          name="status"
          value={filters.status || ''}
          onChange={handleInputChange}
          className="px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
        >
          {statuses.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>

        {/* Min Score */}
        <input
          type="number"
          name="min_score"
          min="0"
          max="100"
          value={filters.min_score || 0}
          onChange={handleInputChange}
          placeholder="Min Score"
          className="px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
        />

        {/* Search */}
        <input
          type="text"
          name="search"
          value={filters.search || ''}
          onChange={handleInputChange}
          placeholder="Search by name"
          className="px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
        />
      </div>

      <div className="flex gap-2">
        <button
          onClick={onApply}
          disabled={isLoading}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400 transition text-sm font-semibold"
        >
          Apply Filters
        </button>
        <button
          onClick={onClear}
          className="px-4 py-2 bg-gray-200 text-gray-800 rounded-lg hover:bg-gray-300 transition text-sm font-semibold"
        >
          Clear Filters
        </button>
      </div>
    </div>
  );
}

/**
 * LeadCountSummary: Shows statistics
 */
function LeadCountSummary({ totalCount, highCount, mediumCount, lowCount, displayingCount }) {
  return (
    <div className="bg-white rounded-lg shadow p-4 mb-4">
      <p className="text-sm text-gray-700">
        <span className="font-semibold">Showing {displayingCount} of {totalCount} leads</span>
        {' '}• High: <span className="font-semibold text-green-600">{highCount}</span>
        {' '}| Medium: <span className="font-semibold text-yellow-600">{mediumCount}</span>
        {' '}| Low: <span className="font-semibold text-gray-600">{lowCount}</span>
      </p>
    </div>
  );
}

/**
 * LeadsTable: Sortable table with pagination
 */
function LeadsTable({
  leads,
  isLoading,
  page,
  pageSize,
  totalCount,
  onPageChange,
  onSort,
  sortField,
  onSelectAll,
  onSelectLead,
  selectedLeads,
  onViewLead,
  onApproveLead,
  onRejectLead,
}) {
  const [sortDirection, setSortDirection] = useState('asc');

  const handleSort = (field) => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortDirection('asc');
    }
    onSort(field, sortDirection === 'asc' ? 'desc' : 'asc');
  };

  const totalPages = Math.ceil(totalCount / pageSize);

  if (isLoading) {
    return (
      <div className="bg-white rounded-lg shadow p-6 text-center">
        <p className="text-gray-500">Loading leads...</p>
      </div>
    );
  }

  if (!leads || leads.length === 0) {
    return (
      <div className="bg-white rounded-lg shadow p-6 text-center">
        <p className="text-gray-500">No leads found — run Scout to find companies</p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg shadow overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-gray-100 border-b">
            <tr>
              <th className="px-4 py-3 text-left">
                <input
                  type="checkbox"
                  onChange={(e) => onSelectAll(e.target.checked)}
                  checked={leads.length > 0 && leads.every((l) => selectedLeads.includes(l.company_id))}
                />
              </th>
              <th
                className="px-4 py-3 text-left font-semibold text-gray-700 cursor-pointer hover:bg-gray-200"
                onClick={() => handleSort('company_name')}
              >
                Company {sortField === 'company_name' && (sortDirection === 'asc' ? '↑' : '↓')}
              </th>
              <th className="px-4 py-3 text-left font-semibold text-gray-700 text-sm">Industry</th>
              <th className="px-4 py-3 text-left font-semibold text-gray-700 text-sm">State</th>
              <th className="px-4 py-3 text-left font-semibold text-gray-700 text-sm">Sites</th>
              <th className="px-4 py-3 text-left font-semibold text-gray-700 text-sm">Annual Spend</th>
              <th className="px-4 py-3 text-left font-semibold text-gray-700 text-sm">Est. Savings</th>
              <th className="px-4 py-3 text-left font-semibold text-gray-700 text-sm">Score</th>
              <th className="px-4 py-3 text-left font-semibold text-gray-700 text-sm">Tier</th>
              <th className="px-4 py-3 text-left font-semibold text-gray-700 text-sm">Status</th>
              <th className="px-4 py-3 text-left font-semibold text-gray-700 text-sm">Contact</th>
              <th className="px-4 py-3 text-left font-semibold text-gray-700 text-sm">Actions</th>
            </tr>
          </thead>
          <tbody>
            {leads.map((lead) => (
              <tr key={lead.company_id} className="border-b hover:bg-gray-50">
                <td className="px-4 py-3">
                  <input
                    type="checkbox"
                    checked={selectedLeads.includes(lead.company_id)}
                    onChange={(e) => onSelectLead(lead.company_id, e.target.checked)}
                  />
                </td>
                <td className="px-4 py-3">
                  <button
                    onClick={() => onViewLead(lead.company_id)}
                    className="font-semibold text-blue-600 hover:underline"
                  >
                    {lead.company_name}
                  </button>
                </td>
                <td className="px-4 py-3 text-sm text-gray-700">{lead.industry || '—'}</td>
                <td className="px-4 py-3 text-sm text-gray-700">{lead.state || '—'}</td>
                <td className="px-4 py-3 text-sm text-gray-700">{lead.site_count || '—'}</td>
                <td className="px-4 py-3 text-sm text-gray-700">
                  {lead.savings_mid_formatted || formatCurrency(lead.estimated_total_spend)}
                </td>
                <td className="px-4 py-3 text-sm text-gray-700">
                  {lead.savings_mid_formatted || formatCurrency(lead.savings_mid)}
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold">{lead.score || '—'}</span>
                    {lead.score && (
                      <div className="w-16 bg-gray-200 rounded-full h-2">
                        <div
                          className="bg-blue-600 h-2 rounded-full"
                          style={{ width: `${lead.score}%` }}
                        />
                      </div>
                    )}
                  </div>
                </td>
                <td className="px-4 py-3">
                  <span
                    className={`px-2 py-1 rounded text-xs font-semibold ${getTierColor(lead.tier)}`}
                  >
                    {lead.tier || '—'}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <span
                    className={`px-2 py-1 rounded text-xs font-semibold ${getStatusColor(lead.status)}`}
                  >
                    {lead.status || '—'}
                  </span>
                </td>
                <td className="px-4 py-3 text-sm text-center">
                  {lead.contact_found ? '✓' : '✗'}
                </td>
                <td className="px-4 py-3 text-sm flex gap-2">
                  <button
                    onClick={() => onViewLead(lead.company_id)}
                    className="text-blue-600 hover:underline"
                  >
                    View
                  </button>
                  {lead.tier === 'high' && lead.status !== 'approved' && (
                    <button
                      onClick={() => onApproveLead(lead.company_id)}
                      className="text-green-600 hover:underline"
                    >
                      Approve
                    </button>
                  )}
                  {lead.status !== 'rejected' && (
                    <button
                      onClick={() => onRejectLead(lead.company_id)}
                      className="text-red-600 hover:underline"
                    >
                      Reject
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="bg-gray-50 px-4 py-3 flex justify-between items-center border-t">
        <p className="text-sm text-gray-600">
          Page {page} of {totalPages}
        </p>
        <div className="flex gap-2">
          <button
            onClick={() => onPageChange(page - 1)}
            disabled={page <= 1}
            className="px-3 py-1 border border-gray-300 rounded hover:bg-gray-100 disabled:opacity-50 text-sm"
          >
            ← Prev
          </button>
          <button
            onClick={() => onPageChange(page + 1)}
            disabled={page >= totalPages}
            className="px-3 py-1 border border-gray-300 rounded hover:bg-gray-100 disabled:opacity-50 text-sm"
          >
            Next →
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * BulkApproveBar: Appears when leads selected
 */
function BulkApproveBar({ selectedCount, highLeadsCount, onBulkApprove, onClearSelection }) {
  if (selectedCount === 0) return null;

  return (
    <div className="bg-blue-100 border border-blue-300 rounded-lg shadow p-4 mb-4 flex justify-between items-center">
      <p className="text-sm font-semibold text-blue-900">
        {selectedCount} lead{selectedCount !== 1 ? 's' : ''} selected ({highLeadsCount} high tier)
      </p>
      <div className="flex gap-2">
        <button
          onClick={onBulkApprove}
          disabled={highLeadsCount === 0}
          className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:bg-gray-400 transition text-sm font-semibold"
        >
          ✓ Approve {highLeadsCount} High Leads
        </button>
        <button
          onClick={onClearSelection}
          className="px-4 py-2 bg-gray-300 text-gray-800 rounded-lg hover:bg-gray-400 transition text-sm font-semibold"
        >
          Clear Selection
        </button>
      </div>
    </div>
  );
}

// ============================================================================
// MAIN COMPONENT
// ============================================================================

/**
 * Leads: Lead intelligence page with table, filters, and bulk actions
 */
export default function Leads() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const [leads, setLeads] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  const [filters, setFilters] = useState({
    industry: searchParams.get('industry') || '',
    state: searchParams.get('state') || '',
    tier: searchParams.get('tier') || '',
    status: searchParams.get('status') || '',
    min_score: parseInt(searchParams.get('min_score'), 10) || 0,
    search: searchParams.get('search') || '',
    page: 1,
    page_size: 25,
  });

  const [pagination, setPagination] = useState({
    page: 1,
    page_size: 25,
    total_count: 0,
  });

  const [summary, setSummary] = useState({
    high_count: 0,
    medium_count: 0,
    low_count: 0,
  });

  const [sortField, setSortField] = useState('company_name');
  const [selectedLeads, setSelectedLeads] = useState([]);
  const [industries, setIndustries] = useState([]);

  /**
   * Load leads with current filters
   */
  const loadLeads = async (filterParams = filters) => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await fetchLeads(filterParams);
      setLeads(response.leads || []);
      setPagination({
        page: response.page || 1,
        page_size: response.page_size || 25,
        total_count: response.total_count || 0,
      });
      setSummary({
        high_count: response.high_count || 0,
        medium_count: response.medium_count || 0,
        low_count: response.low_count || 0,
      });
    } catch (err) {
      console.error('Failed to load leads:', err);
      setError('Failed to load leads. Check API connection.');
    } finally {
      setIsLoading(false);
    }
  };

  /**
   * Load leads and industry list on mount
   */
  useEffect(() => {
    loadLeads();
    fetchIndustries().then(setIndustries).catch(() => {});
  }, []);

  /**
   * Handle filter changes
   */
  const handleFilterChange = (newFilters) => {
    setFilters(newFilters);
  };

  /**
   * Apply filters
   */
  const handleApplyFilters = () => {
    loadLeads(filters);
  };

  /**
   * Clear filters
   */
  const handleClearFilters = () => {
    const cleared = {
      industry: '',
      state: '',
      tier: '',
      status: '',
      min_score: 0,
      search: '',
      page: 1,
      page_size: 25,
    };
    setFilters(cleared);
    loadLeads(cleared);
  };

  /**
   * Handle page change
   */
  const handlePageChange = (newPage) => {
    const newFilters = { ...filters, page: newPage };
    setFilters(newFilters);
    loadLeads(newFilters);
  };

  /**
   * Handle sort
   */
  const handleSort = (field, direction) => {
    setSortField(field);
    const newFilters = { ...filters, sort_by: field, sort_order: direction };
    loadLeads(newFilters);
  };

  /**
   * Select all leads
   */
  const handleSelectAll = (checked) => {
    if (checked) {
      setSelectedLeads(leads.map((l) => l.company_id));
    } else {
      setSelectedLeads([]);
    }
  };

  /**
   * Select individual lead
   */
  const handleSelectLead = (leadId, checked) => {
    if (checked) {
      setSelectedLeads([...selectedLeads, leadId]);
    } else {
      setSelectedLeads(selectedLeads.filter((id) => id !== leadId));
    }
  };

  /**
   * Bulk approve high leads
   */
  const handleBulkApprove = async () => {
    const highLeads = leads.filter(
      (l) => selectedLeads.includes(l.company_id) && l.tier === 'high'
    );

    try {
      await Promise.all(
        highLeads.map((lead) =>
          approveLead(lead.id, 'bulk_approval_user')
        )
      );
      setSelectedLeads([]);
      loadLeads();
    } catch (err) {
      console.error('Bulk approve failed:', err);
      setError('Failed to approve leads. Try again.');
    }
  };

  /**
   * Approve single lead
   */
  const handleApproveLead = async (leadId) => {
    try {
      await approveLead(leadId, 'user');
      loadLeads();
    } catch (err) {
      console.error('Approve failed:', err);
      setError('Failed to approve lead. Try again.');
    }
  };

  /**
   * Reject lead
   */
  const handleRejectLead = async (leadId) => {
    const reason = prompt('Rejection reason:');
    if (!reason) return;

    try {
      await rejectLead(leadId, 'user', reason);
      loadLeads();
    } catch (err) {
      console.error('Reject failed:', err);
      setError('Failed to reject lead. Try again.');
    }
  };

  /**
   * Export CSV
   */
  const handleExport = () => {
    exportTableAsCSV(leads, 'leads.csv');
  };

  /**
   * Get high leads count from selected
   */
  const highLeadsSelected = leads
    .filter((l) => selectedLeads.includes(l.company_id) && l.tier === 'high')
    .length;

  return (
    <div className="h-full overflow-y-auto bg-gray-50 p-6">
      {isLoading && <LoadingOverlay message="Loading leads..." />}
      <div className="max-w-7xl mx-auto">
        {/* Page Header */}
        <PageHeader onExport={handleExport} hasData={leads.length > 0} />

        {/* Error Alert */}
        {error && (
          <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded-lg mb-6 flex items-center justify-between">
            <span>{error}</span>
            <button
              onClick={() => loadLeads()}
              className="ml-4 px-3 py-1 bg-red-600 text-white rounded hover:bg-red-700 text-sm font-medium"
            >
              Retry
            </button>
          </div>
        )}

        {/* Filter Bar */}
        <FilterBar
          filters={filters}
          onFilterChange={handleFilterChange}
          onApply={handleApplyFilters}
          onClear={handleClearFilters}
          isLoading={isLoading}
          industries={industries}
        />

        {/* Lead Count Summary */}
        {!isLoading && leads.length > 0 && (
          <LeadCountSummary
            totalCount={pagination.total_count}
            highCount={summary.high_count}
            mediumCount={summary.medium_count}
            lowCount={summary.low_count}
            displayingCount={leads.length}
          />
        )}

        {/* Bulk Approve Bar */}
        <BulkApproveBar
          selectedCount={selectedLeads.length}
          highLeadsCount={highLeadsSelected}
          onBulkApprove={handleBulkApprove}
          onClearSelection={() => setSelectedLeads([])}
        />

        {/* Leads Table */}
        <LeadsTable
          leads={leads}
          isLoading={isLoading}
          page={pagination.page}
          pageSize={pagination.page_size}
          totalCount={pagination.total_count}
          onPageChange={handlePageChange}
          onSort={handleSort}
          sortField={sortField}
          onSelectAll={handleSelectAll}
          onSelectLead={handleSelectLead}
          selectedLeads={selectedLeads}
          onViewLead={(id) => navigate(`/leads/${id}`)}
          onApproveLead={handleApproveLead}
          onRejectLead={handleRejectLead}
        />
      </div>
    </div>
  );
}
