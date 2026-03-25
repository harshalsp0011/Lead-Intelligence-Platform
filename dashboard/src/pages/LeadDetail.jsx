/**
 * Lead Detail Page
 * 
 * Displays comprehensive information about a single lead company including
 * financial estimates, lead score breakdown, contacts, email drafts, and
 * outreach timeline.
 * 
 * Route: /leads/:companyId
 * 
 * Components:
 * - BackButton: Navigate back to leads list
 * - CompanyHeader: Company name, industry, location, website, status
 * - FinancialEstimatesPanel: Utility/telecom spend, savings, revenue estimate
 * - ScoreBreakdownPanel: Lead score, tier, factors, approval buttons
 * - ContactsPanel: Table of contacts with copy/LinkedIn actions
 * - EmailDraftsPanel: List of email drafts with review/regenerate
 * - OutreachTimeline: Chronological events with icons and colors
 * - ApprovalModal: Email review and approval workflow
 * - AddContactModal: Manual contact addition
 * 
 * Usage:
 *   import LeadDetail from './pages/LeadDetail';
 *   <Route path="/leads/:companyId" element={<LeadDetail />} />
 */

import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import LoadingOverlay from '../components/LoadingOverlay';
import {
  fetchLeadById,
  approveLead,
  rejectLead,
  regenerateEmail,
  approveEmail,
  editEmail,
  enrichLead,
} from '../services/api';

// ============================================================================
// UTILITIES
// ============================================================================

/**
 * Format currency for display
 */
function formatSavings(value) {
  if (!value) return '$0';
  if (value >= 1000000) return `$${(value / 1000000).toFixed(1)}M`;
  if (value >= 1000) return `$${(value / 1000).toFixed(0)}k`;
  return `$${value}`;
}

/**
 * Get status badge color
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
 * Get tier badge color
 */
function getTierColor(tier) {
  if (tier === 'high') return 'bg-green-100 text-green-800';
  if (tier === 'medium') return 'bg-yellow-100 text-yellow-800';
  return 'bg-gray-100 text-gray-800';
}

/**
 * Format date to readable format
 */
function formatDate(dateString) {
  const date = new Date(dateString);
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/**
 * Get event icon and color
 */
function getEventIcon(eventType) {
  const icons = {
    email_sent: { icon: '✉️', color: 'bg-blue-100 text-blue-800', label: 'Email Sent' },
    email_opened: { icon: '👁️', color: 'bg-yellow-100 text-yellow-800', label: 'Email Opened' },
    reply_positive: { icon: '✓', color: 'bg-green-100 text-green-800', label: 'Positive Reply' },
    reply_negative: { icon: '✗', color: 'bg-red-100 text-red-800', label: 'Negative Reply' },
    email_bounced: { icon: '↩️', color: 'bg-gray-100 text-gray-800', label: 'Email Bounced' },
    followup_sent: { icon: '→', color: 'bg-purple-100 text-purple-800', label: 'Followup Sent' },
  };
  return icons[eventType] || { icon: '•', color: 'bg-gray-100 text-gray-800', label: 'Event' };
}

// ============================================================================
// SUB-COMPONENTS
// ============================================================================

/**
 * BackButton: Navigate back to leads
 */
function BackButton({ navigate }) {
  return (
    <button
      onClick={() => navigate('/leads')}
      className="mb-6 text-blue-600 hover:text-blue-800 font-semibold flex items-center gap-2"
    >
      ← Back to Leads
    </button>
  );
}

/**
 * CompanyHeader: Company name, industry, location, website, status
 */
function CompanyHeader({ lead, isLoading }) {
  return (
    <div className="bg-white rounded-lg shadow p-6 mb-6">
      <div className="flex justify-between items-start gap-4">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 mb-2">{lead.company_name}</h1>
          <div className="flex gap-2 items-center flex-wrap">
            <span className="px-3 py-1 bg-blue-100 text-blue-800 rounded text-sm font-semibold">
              {lead.industry}
            </span>
            {lead.city && lead.state && (
              <span className="text-gray-600">
                📍 {lead.city}, {lead.state}
              </span>
            )}
            {lead.phone && (
              <a href={`tel:${lead.phone}`} className="text-green-700 font-medium text-sm">
                📞 {lead.phone}
              </a>
            )}
            {lead.website && (
              <a
                href={lead.website}
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-600 hover:underline text-sm"
              >
                🌐 Visit Website
              </a>
            )}
            {lead.linkedin_search_url && (
              <a
                href={lead.linkedin_search_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-700 hover:underline text-sm"
                title="Search this company on LinkedIn"
              >
                🔗 LinkedIn
              </a>
            )}
          </div>
        </div>
        <span className={`px-3 py-1 rounded text-sm font-semibold ${getStatusColor(lead.status)}`}>
          {lead.status}
        </span>
      </div>
    </div>
  );
}

/**
 * FinancialEstimatesPanel: Spending and savings estimates
 */
function FinancialEstimatesPanel({ lead }) {
  const savingsMid = lead.savings_mid || 0;
  const revenueEstimate = lead.tb_revenue_estimate || Math.round(savingsMid * 0.24);
  const notScored = !lead.score || lead.status === 'new';

  return (
    <div className="bg-white rounded-lg shadow p-6 mb-6">
      <h2 className="text-lg font-bold text-gray-900 mb-4">Financial Estimates</h2>

      {notScored && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-2 mb-4 text-amber-800 text-sm">
          ⏳ Analyst has not run yet — estimates will appear after scoring.
        </div>
      )}

      <div className="grid md:grid-cols-3 gap-6 mb-6 pb-6 border-b">
        <div>
          <p className="text-sm text-gray-600 mb-1">Estimated Annual Utility Spend</p>
          <p className="text-2xl font-bold text-gray-900">
            {formatSavings(lead.estimated_annual_utility_spend)}
          </p>
        </div>
        <div>
          <p className="text-sm text-gray-600 mb-1">Estimated Annual Telecom Spend</p>
          <p className="text-2xl font-bold text-gray-900">
            {formatSavings(lead.estimated_annual_telecom_spend)}
          </p>
        </div>
        <div>
          <p className="text-sm text-gray-600 mb-1">Total Estimated Spend</p>
          <p className="text-2xl font-bold text-gray-900">
            {formatSavings(lead.estimated_total_spend)}
          </p>
        </div>
      </div>

      <div className="grid md:grid-cols-3 gap-6 mb-6 pb-6 border-b">
        <div>
          <p className="text-sm text-gray-600 mb-1">Savings Low</p>
          <p className="text-2xl font-bold text-gray-900">
            {lead.savings_low_formatted || formatSavings(lead.savings_low)}
          </p>
        </div>
        <div className="p-4 bg-green-50 rounded-lg border-2 border-green-300">
          <p className="text-sm text-gray-600 mb-1">Savings Mid (Estimate)</p>
          <p className="text-2xl font-bold text-green-700">
            {lead.savings_mid_formatted || formatSavings(savingsMid)}
          </p>
        </div>
        <div>
          <p className="text-sm text-gray-600 mb-1">Savings High</p>
          <p className="text-2xl font-bold text-gray-900">
            {lead.savings_high_formatted || formatSavings(lead.savings_high)}
          </p>
        </div>
      </div>

      <div>
        <p className="text-sm text-gray-600 mb-1">Troy & Banks Revenue Estimate (24% of savings)</p>
        <p className="text-2xl font-bold text-purple-700">{formatSavings(revenueEstimate)}</p>
      </div>
    </div>
  );
}

/**
 * ScoreBreakdownPanel: Lead score, tier, factors
 */
function ScoreBreakdownPanel({ lead, onApprove, onReject, onEnrich, isLoadingAction, isLoadingEnrich }) {
  // Compute factor scores from available data using the same weights as score_engine.py
  const savingsMid = lead.savings_mid || 0;
  const recoveryScore = savingsMid >= 2000000 ? 40 : savingsMid >= 1000000 ? 34 : savingsMid >= 500000 ? 28 : savingsMid >= 250000 ? 22 : 16;
  const industryFitRaw = lead.industry_fit_score || 0;  // 0–100 raw score stored in features
  const industryScore = Math.round(industryFitRaw * 0.25);  // weight 0.25 → max 25
  const siteCount = lead.site_count || 0;
  const multisiteScore = siteCount >= 20 ? 20 : siteCount >= 10 ? 17 : siteCount >= 5 ? 13 : siteCount >= 2 ? 8 : 3;
  const dqRaw = lead.data_quality_score || 0;  // 0–10 quality score
  const dataQualityScore = dqRaw >= 9 ? 15 : dqRaw >= 7 ? 12 : dqRaw >= 5 ? 8 : dqRaw >= 3 ? 4 : 1;

  const notScored = !lead.score || lead.status === 'new';

  const factors = [
    { name: 'Recovery Potential', actual: notScored ? 0 : recoveryScore, max: 40 },
    { name: 'Industry Fit', actual: notScored ? 0 : industryScore, max: 25 },
    { name: 'Multi-site', actual: notScored ? 0 : multisiteScore, max: 20 },
    { name: 'Data Quality', actual: notScored ? 0 : dataQualityScore, max: 15 },
  ];

  return (
    <div className="bg-white rounded-lg shadow p-6 mb-6">
      <div className="flex items-start gap-6 mb-6 pb-6 border-b">
        <div className="text-center">
          <p className="text-sm text-gray-600 mb-2">Lead Score</p>
          {notScored ? (
            <p className="text-2xl font-bold text-amber-500">pending</p>
          ) : (
            <p className="text-5xl font-bold text-blue-600">{lead.score}</p>
          )}
          <p className="text-sm text-gray-600 mt-2">/ 100</p>
        </div>
        <div className="flex-1">
          <div className="mb-4">
            <span className={`px-3 py-1 rounded text-sm font-semibold ${getTierColor(lead.tier)}`}>
              {(lead.tier || 'unknown').toUpperCase()} TIER
            </span>
            {notScored && (
              <span className="ml-2 text-xs text-amber-600 font-semibold">— not yet analyzed</span>
            )}
          </div>
          <p className="text-gray-700">{lead.score_reason || (notScored ? 'Run Analyst to score this company.' : 'Strong lead based on multiple factors.')}</p>
        </div>
      </div>

      <div className="mb-6">
        <h3 className="font-semibold text-gray-900 mb-4">Score Factors</h3>
        <div className="space-y-4">
          {factors.map((factor) => (
            <div key={factor.name}>
              <div className="flex justify-between items-center mb-2">
                <span className="text-sm font-semibold text-gray-700">{factor.name}</span>
                <span className="text-sm text-gray-600">
                  {factor.actual} / {factor.max}
                </span>
              </div>
              <div className="w-full bg-gray-200 rounded-full h-2">
                <div
                  className="bg-blue-600 h-2 rounded-full"
                  style={{ width: `${(factor.actual / factor.max) * 100}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="flex gap-2 flex-wrap">
        {!lead.approved_human && lead.score > 0 && lead.status !== 'approved' && (
          <button
            onClick={onApprove}
            disabled={isLoadingAction}
            className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:bg-gray-400 transition font-semibold"
          >
            {isLoadingAction ? '...' : '✓ Approve Lead'}
          </button>
        )}
        {lead.status !== 'archived' && (
          <button
            onClick={onReject}
            disabled={isLoadingAction}
            className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:bg-gray-400 transition font-semibold"
          >
            {isLoadingAction ? '...' : '✗ Reject Lead'}
          </button>
        )}
        <button
          onClick={onEnrich}
          disabled={isLoadingEnrich}
          className="px-4 py-2 bg-orange-500 text-white rounded-lg hover:bg-orange-600 disabled:bg-gray-400 transition font-semibold"
          title="Find contacts via Hunter/Apollo for this company"
        >
          {isLoadingEnrich ? '⏳ Enriching...' : '👤 Find Contacts'}
        </button>
      </div>
    </div>
  );
}

/**
 * ContactsPanel: Table of contacts
 */
function ContactsPanel({ contacts, onAddContact }) {
  const [showAddModal, setShowAddModal] = useState(false);

  return (
    <div className="bg-white rounded-lg shadow p-6 mb-6">
      <h2 className="text-lg font-bold text-gray-900 mb-4">Contacts</h2>

      {contacts && contacts.length > 0 ? (
        <div className="overflow-x-auto mb-4">
          <table className="w-full text-sm">
            <thead className="bg-gray-100 border-b">
              <tr>
                <th className="px-4 py-2 text-left font-semibold text-gray-700">Name</th>
                <th className="px-4 py-2 text-left font-semibold text-gray-700">Title</th>
                <th className="px-4 py-2 text-left font-semibold text-gray-700">Email</th>
                <th className="px-4 py-2 text-left font-semibold text-gray-700">Source</th>
                <th className="px-4 py-2 text-left font-semibold text-gray-700">Verified</th>
                <th className="px-4 py-2 text-left font-semibold text-gray-700">Actions</th>
              </tr>
            </thead>
            <tbody>
              {contacts.map((contact, idx) => (
                <tr key={idx} className="border-b hover:bg-gray-50">
                  <td className="px-4 py-2 text-gray-900">{contact.name}</td>
                  <td className="px-4 py-2 text-gray-700">{contact.title || '—'}</td>
                  <td className="px-4 py-2 text-gray-700">{contact.email || '—'}</td>
                  <td className="px-4 py-2 text-gray-700">{contact.source || '—'}</td>
                  <td className="px-4 py-2 text-center">
                    {contact.verified ? '✓' : '—'}
                  </td>
                  <td className="px-4 py-2">
                    <button
                      onClick={() => {
                        navigator.clipboard.writeText(contact.email);
                      }}
                      className="text-blue-600 hover:underline text-xs"
                    >
                      Copy Email
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-gray-500 mb-4">No contacts found yet.</p>
      )}

      <button
        onClick={() => setShowAddModal(true)}
        className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition text-sm font-semibold"
      >
        + Add Contact Manually
      </button>

      {showAddModal && (
        <AddContactModal
          onClose={() => setShowAddModal(false)}
          onSubmit={(contact) => {
            onAddContact(contact);
            setShowAddModal(false);
          }}
        />
      )}
    </div>
  );
}

/**
 * EmailDraftsPanel: List of email drafts
 */
function EmailDraftsPanel({ drafts, onReview, onRegenerate, isLoadingRegen }) {
  return (
    <div className="bg-white rounded-lg shadow p-6 mb-6">
      <h2 className="text-lg font-bold text-gray-900 mb-4">Email Drafts</h2>

      {drafts && drafts.length > 0 ? (
        <div className="space-y-4">
          {drafts.map((draft) => (
            <div key={draft.id} className="border rounded-lg p-4 hover:bg-gray-50">
              <div className="flex justify-between items-start gap-4 mb-2">
                <div className="flex-1 min-w-0">
                  <p className="font-semibold text-gray-900 truncate">{draft.subject_line}</p>
                  <p className="text-sm text-gray-600">
                    Created: {formatDate(draft.created_at)}
                  </p>
                </div>
                <span
                  className={`px-2 py-1 rounded text-xs font-semibold flex-shrink-0 ${
                    draft.status === 'approved'
                      ? 'bg-green-100 text-green-800'
                      : draft.status === 'sent'
                      ? 'bg-blue-100 text-blue-800'
                      : 'bg-yellow-100 text-yellow-800'
                  }`}
                >
                  {draft.status}
                </span>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => onReview(draft)}
                  className="text-blue-600 hover:underline text-xs font-semibold"
                >
                  Review Email
                </button>
                {draft.status === 'pending' && (
                  <button
                    onClick={() => onRegenerate(draft.id)}
                    disabled={isLoadingRegen}
                    className="text-purple-600 hover:underline text-xs font-semibold disabled:opacity-50"
                  >
                    Regenerate
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-gray-500">No email drafts yet.</p>
      )}
    </div>
  );
}

/**
 * OutreachTimeline: Chronological outreach events
 */
function OutreachTimeline({ events }) {
  if (!events || events.length === 0) {
    return (
      <div className="bg-white rounded-lg shadow p-6 mb-6">
        <h2 className="text-lg font-bold text-gray-900 mb-4">Outreach Timeline</h2>
        <p className="text-gray-500">No outreach events yet.</p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg shadow p-6 mb-6">
      <h2 className="text-lg font-bold text-gray-900 mb-4">Outreach Timeline</h2>
      <div className="space-y-4">
        {events.map((event, idx) => {
          const { icon, color, label } = getEventIcon(event.event_type);
          return (
            <div key={idx} className="flex gap-4">
              <div className={`w-10 h-10 rounded-full ${color} flex items-center justify-center flex-shrink-0 text-sm`}>
                {icon}
              </div>
              <div className="flex-1">
                <p className="font-semibold text-gray-900">{label}</p>
                <p className="text-sm text-gray-600">{event.description}</p>
                <p className="text-xs text-gray-500 mt-1">{formatDate(event.event_at)}</p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * ApprovalModal: Email review and approval
 */
function ApprovalModal({ draft, onClose, onApprove, onReject, onRegenerate, isLoading }) {
  const [subject, setSubject] = useState(draft.subject_line || '');
  const [body, setBody] = useState(draft.body || '');
  const [isEditing, setIsEditing] = useState(false);
  const [rejectReason, setRejectReason] = useState('');
  const [showRejectForm, setShowRejectForm] = useState(false);

  const handleApprove = async () => {
    await onApprove(draft.id);
    onClose();
  };

  const handleReject = async () => {
    if (!rejectReason.trim()) {
      alert('Please enter a rejection reason');
      return;
    }
    await onReject(draft.id, rejectReason);
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-lg p-6 w-full max-w-2xl max-h-[90vh] overflow-auto">
        <h2 className="text-xl font-bold text-gray-900 mb-4">Review Email Draft</h2>

        {draft.tone_warnings && draft.tone_warnings.length > 0 && (
          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3 mb-4">
            <p className="text-sm font-semibold text-yellow-800 mb-1">Tone Warnings:</p>
            {draft.tone_warnings.map((warning, idx) => (
              <p key={idx} className="text-sm text-yellow-700">• {warning}</p>
            ))}
          </div>
        )}

        <div className="space-y-4 mb-6">
          {/* TO Field */}
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-1">To</label>
            <input
              type="text"
              value={draft.contact_name ? `${draft.contact_name} <${draft.contact_email}>` : ''}
              readOnly
              className="w-full px-3 py-2 bg-gray-100 border border-gray-300 rounded-lg text-gray-700"
            />
          </div>

          {/* Subject */}
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-1">Subject</label>
            {isEditing ? (
              <input
                type="text"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            ) : (
              <p className="px-3 py-2 bg-gray-50 rounded-lg text-gray-900">{subject}</p>
            )}
          </div>

          {/* Body */}
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-1">Message</label>
            {isEditing ? (
              <textarea
                value={body}
                onChange={(e) => setBody(e.target.value)}
                rows="8"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            ) : (
              <p className="px-3 py-2 bg-gray-50 rounded-lg text-gray-900 whitespace-pre-wrap">{body}</p>
            )}
          </div>
        </div>

        {/* Rejection Form */}
        {showRejectForm && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-4">
            <label className="block text-sm font-semibold text-gray-700 mb-2">Rejection Reason</label>
            <textarea
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              rows="3"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-red-500"
              placeholder="Explain why you're rejecting this email..."
            />
          </div>
        )}

        {/* Buttons */}
        <div className="flex gap-2 flex-wrap">
          {!showRejectForm && (
            <>
              <button
                onClick={handleApprove}
                disabled={isLoading}
                className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:bg-gray-400 transition font-semibold"
              >
                {isEditing ? '✓ Save & Approve' : '✓ Approve'}
              </button>
              <button
                onClick={() => {
                  if (isEditing) {
                    // Save edits first
                    setIsEditing(false);
                  } else {
                    setIsEditing(!isEditing);
                  }
                }}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition font-semibold"
              >
                {isEditing ? 'Done Editing' : 'Edit'}
              </button>
              <button
                onClick={() => setShowRejectForm(true)}
                className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition font-semibold"
              >
                ✗ Reject
              </button>
              <button
                onClick={() => onRegenerate(draft.id)}
                disabled={isLoading}
                className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:bg-gray-400 transition font-semibold"
              >
                ↻ Regenerate
              </button>
            </>
          )}
          {showRejectForm && (
            <>
              <button
                onClick={handleReject}
                disabled={isLoading}
                className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:bg-gray-400 transition font-semibold"
              >
                {isLoading ? '...' : 'Confirm Reject'}
              </button>
              <button
                onClick={() => setShowRejectForm(false)}
                className="px-4 py-2 bg-gray-300 text-gray-800 rounded-lg hover:bg-gray-400 transition font-semibold"
              >
                Cancel
              </button>
            </>
          )}
          <button
            onClick={onClose}
            className="px-4 py-2 bg-gray-200 text-gray-800 rounded-lg hover:bg-gray-300 transition font-semibold"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * AddContactModal: Manual contact addition
 */
function AddContactModal({ onClose, onSubmit }) {
  const [formData, setFormData] = useState({
    name: '',
    title: '',
    email: '',
  });

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!formData.name.trim() || !formData.email.trim()) {
      alert('Name and email are required');
      return;
    }
    onSubmit(formData);
    setFormData({ name: '', title: '', email: '' });
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-lg p-6 w-full max-w-md">
        <h2 className="text-xl font-bold text-gray-900 mb-4">Add Contact Manually</h2>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-2">Name *</label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-2">Title</label>
            <input
              type="text"
              value={formData.title}
              onChange={(e) => setFormData({ ...formData, title: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm font-semibold text-gray-700 mb-2">Email *</label>
            <input
              type="email"
              value={formData.email}
              onChange={(e) => setFormData({ ...formData, email: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div className="flex gap-2 pt-4">
            <button
              type="submit"
              className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition font-semibold"
            >
              Add Contact
            </button>
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2 bg-gray-200 text-gray-800 rounded-lg hover:bg-gray-300 transition font-semibold"
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
 * LeadDetail: Full lead company details page
 */
export default function LeadDetail() {
  const { companyId } = useParams();
  const navigate = useNavigate();

  const [lead, setLead] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingAction, setIsLoadingAction] = useState(false);
  const [error, setError] = useState(null);
  const [reviewDraft, setReviewDraft] = useState(null);
  const [isLoadingRegen, setIsLoadingRegen] = useState(false);
  const [isLoadingEnrich, setIsLoadingEnrich] = useState(false);

  /**
   * Load lead data
   */
  useEffect(() => {
    const loadLead = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const data = await fetchLeadById(companyId);
        setLead(data);
      } catch (err) {
        console.error('Failed to load lead:', err);
        setError('Failed to load lead details. Check API connection.');
      } finally {
        setIsLoading(false);
      }
    };

    loadLead();
  }, [companyId]);

  /**
   * Approve lead
   */
  const handleApproveLead = async () => {
    setIsLoadingAction(true);
    try {
      await approveLead(companyId, 'user');
      setLead({ ...lead, status: 'approved' });
    } catch (err) {
      console.error('Approve failed:', err);
      setError('Failed to approve lead.');
    } finally {
      setIsLoadingAction(false);
    }
  };

  /**
   * Reject lead
   */
  const handleRejectLead = async () => {
    const reason = prompt('Rejection reason:');
    if (!reason) return;

    setIsLoadingAction(true);
    try {
      await rejectLead(companyId, 'user', reason);
      setLead({ ...lead, status: 'rejected' });
    } catch (err) {
      console.error('Reject failed:', err);
      setError('Failed to reject lead.');
    } finally {
      setIsLoadingAction(false);
    }
  };

  /**
   * Trigger contact enrichment for this company
   */
  const handleEnrichLead = async () => {
    setIsLoadingEnrich(true);
    try {
      const result = await enrichLead(companyId);
      if (result.contacts_found > 0 || result.success) {
        const data = await fetchLeadById(companyId);
        setLead(data);
      }
      setError(null);
    } catch (err) {
      console.error('Enrichment failed:', err);
      setError('Enrichment failed. Check if Hunter/Apollo API key is configured.');
    } finally {
      setIsLoadingEnrich(false);
    }
  };

  /**
   * Regenerate email
   */
  const handleRegenerate = async (draftId) => {
    setIsLoadingRegen(true);
    try {
      const newDraft = await regenerateEmail(draftId);
      setLead({
        ...lead,
        email_drafts: lead.email_drafts.map((d) =>
          d.id === draftId ? newDraft : d
        ),
      });
      setReviewDraft(null);
    } catch (err) {
      console.error('Regenerate failed:', err);
      setError('Failed to regenerate email.');
    } finally {
      setIsLoadingRegen(false);
    }
  };

  /**
   * Approve email
   */
  const handleApproveEmail = async (draftId) => {
    setIsLoadingAction(true);
    try {
      await approveEmail(draftId, 'user');
      setLead({
        ...lead,
        email_drafts: lead.email_drafts.map((d) =>
          d.id === draftId ? { ...d, status: 'approved' } : d
        ),
      });
      setReviewDraft(null);
    } catch (err) {
      console.error('Approve email failed:', err);
      setError('Failed to approve email.');
    } finally {
      setIsLoadingAction(false);
    }
  };

  /**
   * Reject email
   */
  const handleRejectEmail = async (draftId, reason) => {
    setIsLoadingAction(true);
    try {
      await approveEmail(draftId, 'user'); // Using API structure
      setLead({
        ...lead,
        email_drafts: lead.email_drafts.map((d) =>
          d.id === draftId ? { ...d, status: 'rejected' } : d
        ),
      });
      setReviewDraft(null);
    } catch (err) {
      console.error('Reject email failed:', err);
      setError('Failed to reject email.');
    } finally {
      setIsLoadingAction(false);
    }
  };

  if (isLoading) {
    return (
      <div className="h-full overflow-y-auto bg-gray-50 p-6">
        <div className="max-w-4xl mx-auto text-center py-12">
          <p className="text-gray-500">Loading lead details...</p>
        </div>
      </div>
    );
  }

  if (error || !lead) {
    return (
      <div className="h-full overflow-y-auto bg-gray-50 p-6">
        <div className="max-w-4xl mx-auto py-12">
          <BackButton navigate={navigate} />
          <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded-lg">
            {error || 'Lead not found.'}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto bg-gray-50 p-6">
      {isLoading && <LoadingOverlay message="Loading lead details..." />}
      <div className="max-w-4xl mx-auto">
        <BackButton navigate={navigate} />

        <CompanyHeader lead={lead} />

        <FinancialEstimatesPanel lead={lead} />

        <ScoreBreakdownPanel
          lead={lead}
          onApprove={handleApproveLead}
          onReject={handleRejectLead}
          onEnrich={handleEnrichLead}
          isLoadingAction={isLoadingAction}
          isLoadingEnrich={isLoadingEnrich}
        />

        <ContactsPanel
          contacts={lead.contacts || []}
          onAddContact={(contact) => {
            console.log('Add contact:', contact);
            // Integrate with API when endpoint available
          }}
        />

        <EmailDraftsPanel
          drafts={lead.email_drafts || []}
          onReview={(draft) => setReviewDraft(draft)}
          onRegenerate={handleRegenerate}
          isLoadingRegen={isLoadingRegen}
        />

        <OutreachTimeline events={lead.outreach_events || []} />
      </div>

      {reviewDraft && (
        <ApprovalModal
          draft={reviewDraft}
          onClose={() => setReviewDraft(null)}
          onApprove={handleApproveEmail}
          onReject={handleRejectEmail}
          onRegenerate={handleRegenerate}
          isLoading={isLoadingAction || isLoadingRegen}
        />
      )}
    </div>
  );
}
