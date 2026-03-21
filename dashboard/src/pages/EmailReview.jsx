/**
 * Email Review Page
 * 
 * Human approval checkpoint for pending email drafts before sending.
 * Allows reviewers to approve, edit, reject, or regenerate drafts.
 * Supports bulk approval of high-score leads.
 * 
 * Route: /emails/review
 * 
 * Components:
 * - PageHeader: Title, subtitle, pending count badge
 * - PendingCountBanner: Info/success banner based on queue status
 * - BulkApproveSection: Select all, bulk approve with progress
 * - EmailReviewCards: Individual draft review and approval workflow
 * 
 * Usage:
 *   import EmailReview from './pages/EmailReview';
 *   <Route path="/emails/review" element={<EmailReview />} />
 */

import React, { useState, useEffect } from 'react';
import LoadingOverlay from '../components/LoadingOverlay';
import {
  fetchPendingEmails,
  approveEmail,
  rejectEmail,
  regenerateEmail,
  editEmail,
} from '../services/api';

// ============================================================================
// UTILITIES
// ============================================================================

/**
 * Format currency
 */
function formatSavings(value) {
  if (!value) return '$0';
  if (value >= 1000000) return `$${(value / 1000000).toFixed(1)}M`;
  if (value >= 1000) return `$${(value / 1000).toFixed(0)}k`;
  return `$${value}`;
}

/**
 * Get tier badge color
 */
function getTierColor(tier) {
  if (tier === 'high') return 'bg-green-100 text-green-800';
  if (tier === 'medium') return 'bg-yellow-100 text-yellow-800';
  return 'bg-gray-100 text-gray-800';
}

// ============================================================================
// SUB-COMPONENTS
// ============================================================================

/**
 * PageHeader: Title and pending count
 */
function PageHeader({ pendingCount }) {
  return (
    <div className="flex justify-between items-start mb-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Email Review Queue</h1>
        <p className="text-gray-600 mt-1">Review and approve emails before sending</p>
      </div>
      <div className="bg-blue-100 text-blue-800 px-4 py-2 rounded-full font-bold">
        {pendingCount} pending
      </div>
    </div>
  );
}

/**
 * PendingCountBanner: Info or success banner
 */
function PendingCountBanner({ pendingCount }) {
  if (pendingCount > 0) {
    return (
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6 text-blue-900">
        <p className="font-semibold">
          You have <span className="text-lg font-bold">{pendingCount}</span> emails waiting for your review.
        </p>
        <p className="text-sm mt-1">All emails require approval before sending.</p>
      </div>
    );
  }

  return (
    <div className="bg-green-50 border border-green-200 rounded-lg p-4 mb-6 text-green-900">
      <p className="font-semibold">✓ All caught up — no emails pending review</p>
    </div>
  );
}

/**
 * BulkApproveSection: Select and approve all high-score leads
 */
function BulkApproveSection({
  emails,
  selectedCount,
  onToggleSelectAll,
  onBulkApprove,
  isApproving,
  approvalProgress,
  approvedCount,
}) {
  const highScoreEmails = emails.filter((e) => e.lead_score >= 80).length;
  const allHighSelected =
    highScoreEmails > 0 &&
    emails.filter((e) => e.lead_score >= 80).every((e) => e.selected);

  return (
    <div className="bg-white rounded-lg shadow p-4 mb-6">
      <div className="flex items-center justify-between gaps-4">
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={allHighSelected}
              onChange={(e) => onToggleSelectAll(e.target.checked)}
              className="w-5 h-5"
            />
            <span className="font-semibold text-gray-700">
              Select all High score leads ({highScoreEmails})
            </span>
          </label>
        </div>

        <div className="flex items-center gap-4">
          {approvalProgress > 0 && approvalProgress < 100 && (
            <div className="flex items-center gap-2">
              <div className="w-32 bg-gray-200 rounded-full h-2">
                <div
                  className="bg-green-600 h-2 rounded-full transition-all"
                  style={{ width: `${approvalProgress}%` }}
                />
              </div>
              <span className="text-xs font-semibold text-gray-600">
                {approvedCount}/{selectedCount}
              </span>
            </div>
          )}

          <button
            onClick={onBulkApprove}
            disabled={selectedCount === 0 || isApproving}
            className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:bg-gray-400 transition font-semibold"
          >
            {isApproving ? '⏳ Approving...' : '✓ Approve All Selected'}
          </button>
        </div>
      </div>

      {approvedCount > 0 && approvalProgress === 100 && (
        <p className="mt-3 text-sm text-green-700 font-semibold">
          ✓ {approvedCount} of {selectedCount} approved this session
        </p>
      )}
    </div>
  );
}

/**
 * EmailReviewCard: Individual email draft review
 */
function EmailReviewCard({
  email,
  onApprove,
  onReject,
  onRegenerate,
  isLoading,
  onToggleSelect,
  isSelected,
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [subject, setSubject] = useState(email.subject_line || '');
  const [body, setBody] = useState(email.body || '');
  const [showRejectForm, setShowRejectForm] = useState(false);
  const [rejectReason, setRejectReason] = useState('');

  const handleApprove = async () => {
    await onApprove(email.id);
  };

  const handleEditAndApprove = async () => {
    if (isEditing) {
      // Save edits and approve
      await onApprove(email.id, subject, body);
      setIsEditing(false);
    } else {
      setIsEditing(true);
    }
  };

  const handleReject = async () => {
    if (!rejectReason.trim()) {
      alert('Please enter a rejection reason');
      return;
    }
    await onReject(email.id, rejectReason);
    setShowRejectForm(false);
  };

  return (
    <div className="bg-white rounded-lg shadow p-6 mb-4">
      {/* Header with selection */}
      <div className="flex items-start gap-4 mb-4 pb-4 border-b">
        <input
          type="checkbox"
          checked={isSelected}
          onChange={(e) => onToggleSelect(email.id, e.target.checked)}
          className="w-5 h-5 mt-1"
        />

        {/* Left section: Company info */}
        <div className="flex-1">
          <h3 className="text-xl font-bold text-gray-900 mb-2">{email.company_name}</h3>
          <div className="flex gap-2 items-center flex-wrap mb-3">
            <span className="px-2 py-1 bg-blue-100 text-blue-800 rounded text-xs font-semibold">
              {email.industry}
            </span>
            <span className={`px-2 py-1 rounded text-xs font-semibold ${getTierColor(email.tier)}`}>
              {email.tier}
            </span>
          </div>

          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <p className="text-gray-600">Score</p>
              <p className="font-bold text-gray-900">{email.lead_score}/100</p>
            </div>
            <div>
              <p className="text-gray-600">Est. Savings</p>
              <p className="font-bold text-gray-900">
                {formatSavings(email.savings_low)} - {formatSavings(email.savings_high)}
              </p>
            </div>
            <div>
              <p className="text-gray-600">Est. TB Revenue</p>
              <p className="font-bold text-gray-900">{formatSavings(email.revenue_estimate)}</p>
            </div>
          </div>
        </div>

        {/* Right section: Email details */}
        <div className="flex-1 min-w-0">
          <div className="space-y-3">
            {/* TO Field */}
            <div>
              <p className="text-xs font-semibold text-gray-600 mb-1">TO</p>
              <p className="text-sm text-gray-900">
                {email.contact_name} — {email.contact_title || 'Contact'}
              </p>
              <p className="text-sm text-gray-600">{email.contact_email}</p>
            </div>

            {/* Subject */}
            <div>
              <label className="text-xs font-semibold text-gray-600 mb-1 block">SUBJECT</label>
              {isEditing ? (
                <input
                  type="text"
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  className="w-full px-2 py-1 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              ) : (
                <p className="text-sm text-gray-900 bg-gray-50 px-2 py-1 rounded">
                  {subject}
                </p>
              )}
            </div>

            {/* Body */}
            <div>
              <label className="text-xs font-semibold text-gray-600 mb-1 block">BODY</label>
              {isEditing ? (
                <textarea
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  rows="5"
                  className="w-full px-2 py-1 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              ) : (
                <div className="text-sm text-gray-900 bg-gray-50 px-2 py-2 rounded max-h-32 overflow-y-auto whitespace-pre-wrap">
                  {body}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Rejection form */}
      {showRejectForm && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-4">
          <label className="block text-sm font-semibold text-gray-700 mb-2">
            Rejection Reason
          </label>
          <textarea
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
            rows="3"
            className="w-full px-3 py-2 border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-red-500 text-sm"
            placeholder="Explain why you're rejecting this email..."
          />
        </div>
      )}

      {/* Action buttons */}
      <div className="flex gap-2 flex-wrap">
        {!showRejectForm && (
          <>
            <button
              onClick={handleApprove}
              disabled={isLoading}
              className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:bg-gray-400 transition font-semibold text-sm"
            >
              ✓ Approve
            </button>

            <button
              onClick={handleEditAndApprove}
              disabled={isLoading}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400 transition font-semibold text-sm"
            >
              {isEditing ? 'Save & Approve' : 'Edit & Approve'}
            </button>

            <button
              onClick={() => setShowRejectForm(true)}
              className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition font-semibold text-sm"
            >
              ✗ Reject
            </button>

            <button
              onClick={() => onRegenerate(email.id)}
              disabled={isLoading}
              className="px-4 py-2 bg-gray-600 text-white rounded-lg hover:bg-gray-700 disabled:bg-gray-400 transition font-semibold text-sm"
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
              className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:bg-gray-400 transition font-semibold text-sm"
            >
              {isLoading ? '...' : 'Confirm Reject'}
            </button>
            <button
              onClick={() => {
                setShowRejectForm(false);
                setRejectReason('');
              }}
              className="px-4 py-2 bg-gray-300 text-gray-800 rounded-lg hover:bg-gray-400 transition font-semibold text-sm"
            >
              Cancel
            </button>
          </>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// MAIN COMPONENT
// ============================================================================

/**
 * EmailReview: Email approval queue page
 */
export default function EmailReview() {
  const [emails, setEmails] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isApproving, setIsApproving] = useState(false);
  const [error, setError] = useState(null);
  const [selectedEmails, setSelectedEmails] = useState(new Set());
  const [approvalProgress, setApprovalProgress] = useState(0);
  const [approvedCount, setApprovedCount] = useState(0);

  /**
   * Load pending emails
   */
  const loadPendingEmails = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await fetchPendingEmails();
      const emailsWithSelected = (response.data || []).map((email) => ({
        ...email,
        selected: false,
      }));
      setEmails(emailsWithSelected);
      setSelectedEmails(new Set());
      setApprovedCount(0);
      setApprovalProgress(0);
    } catch (err) {
      console.error('Failed to load pending emails:', err);
      setError('Failed to load emails. Check API connection.');
    } finally {
      setIsLoading(false);
    }
  };

  /**
   * Load on mount
   */
  useEffect(() => {
    loadPendingEmails();
  }, []);

  /**
   * Toggle all high-score leads
   */
  const handleToggleSelectAll = (checked) => {
    const highScoreEmails = emails.filter((e) => e.lead_score >= 80);
    if (checked) {
      const newSelected = new Set([...selectedEmails]);
      highScoreEmails.forEach((email) => newSelected.add(email.id));
      setSelectedEmails(newSelected);
    } else {
      const newSelected = new Set([...selectedEmails]);
      highScoreEmails.forEach((email) => newSelected.delete(email.id));
      setSelectedEmails(newSelected);
    }
  };

  /**
   * Toggle individual email selection
   */
  const handleToggleSelect = (emailId, checked) => {
    const newSelected = new Set([...selectedEmails]);
    if (checked) {
      newSelected.add(emailId);
    } else {
      newSelected.delete(emailId);
    }
    setSelectedEmails(newSelected);
  };

  /**
   * Bulk approve selected emails
   */
  const handleBulkApprove = async () => {
    if (selectedEmails.size === 0) return;

    setIsApproving(true);
    setApprovalProgress(0);
    let approved = 0;

    const selectedArray = Array.from(selectedEmails);
    try {
      for (let i = 0; i < selectedArray.length; i++) {
        const draftId = selectedArray[i];
        try {
          await approveEmail(draftId, 'bulk_approval');
          approved++;
        } catch (err) {
          console.error(`Failed to approve email ${draftId}:`, err);
        }
        setApprovalProgress(Math.round(((i + 1) / selectedArray.length) * 100));
      }

      setApprovedCount(approved);
      // Reload after all approvals
      setTimeout(() => loadPendingEmails(), 500);
    } catch (err) {
      console.error('Bulk approve failed:', err);
      setError('Some emails failed to approve. Try again.');
    } finally {
      setIsApproving(false);
    }
  };

  /**
   * Approve single email
   */
  const handleApproveEmail = async (draftId, newSubject, newBody) => {
    try {
      // If edited, save edits first
      if (newSubject || newBody) {
        await editEmail(draftId, 'user', newSubject, newBody);
      }
      await approveEmail(draftId, 'user');
      setEmails(emails.filter((e) => e.id !== draftId));
      setSelectedEmails(
        new Set([...selectedEmails].filter((id) => id !== draftId))
      );
    } catch (err) {
      console.error('Approve failed:', err);
      setError('Failed to approve email. Try again.');
    }
  };

  /**
   * Reject email
   */
  const handleRejectEmail = async (draftId, reason) => {
    try {
      await rejectEmail(draftId, 'user', reason);
      setEmails(emails.filter((e) => e.id !== draftId));
      setSelectedEmails(
        new Set([...selectedEmails].filter((id) => id !== draftId))
      );
    } catch (err) {
      console.error('Reject failed:', err);
      setError('Failed to reject email. Try again.');
    }
  };

  /**
   * Regenerate email
   */
  const handleRegenerate = async (draftId) => {
    try {
      const newDraft = await regenerateEmail(draftId);
      setEmails(
        emails.map((e) =>
          e.id === draftId
            ? { ...newDraft, selected: e.selected }
            : e
        )
      );
    } catch (err) {
      console.error('Regenerate failed:', err);
      setError('Failed to regenerate email. Try again.');
    }
  };

  if (isLoading) {
    return (
      <div className="h-full overflow-y-auto bg-gray-50 p-6">
        <div className="max-w-6xl mx-auto text-center py-12">
          <p className="text-gray-500">Loading emails...</p>
        </div>
      </div>
    );
  }

  const emailsWithSelected = emails.map((e) => ({
    ...e,
    selected: selectedEmails.has(e.id),
  }));

  return (
    <div className="h-full overflow-y-auto bg-gray-50 p-6">
      {isLoading && <LoadingOverlay message="Loading emails..." />}
      <div className="max-w-6xl mx-auto">
        <PageHeader pendingCount={emails.length} />

        {error && (
          <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded-lg mb-6">
            {error}
          </div>
        )}

        <PendingCountBanner pendingCount={emails.length} />

        {emails.length > 0 && (
          <BulkApproveSection
            emails={emailsWithSelected}
            selectedCount={selectedEmails.size}
            onToggleSelectAll={handleToggleSelectAll}
            onBulkApprove={handleBulkApprove}
            isApproving={isApproving}
            approvalProgress={approvalProgress}
            approvedCount={approvedCount}
          />
        )}

        {emails.length > 0 ? (
          <div>
            {emailsWithSelected.map((email) => (
              <EmailReviewCard
                key={email.id}
                email={email}
                onApprove={handleApproveEmail}
                onReject={handleRejectEmail}
                onRegenerate={handleRegenerate}
                isLoading={isApproving}
                onToggleSelect={handleToggleSelect}
                isSelected={selectedEmails.has(email.id)}
              />
            ))}
          </div>
        ) : (
          <div className="bg-white rounded-lg shadow p-12 text-center">
            <p className="text-gray-500 text-lg">
              ✓ All caught up — no emails pending review
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
