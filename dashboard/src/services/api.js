/**
 * API Service Layer
 * 
 * Handles all HTTP requests from the React frontend to the FastAPI backend.
 * Provides 20 functions for leads, emails, pipeline management, triggering campaigns,
 * reporting, and health checks.
 * 
 * Configuration:
 * - BASE_URL: http://localhost:8001 (configurable via REACT_APP_API_URL env var)
 * - Default headers: Content-Type: application/json
 * - Timeout: 30 seconds for all requests
 * - Error handling: Special cases for 401 (auth), 500 (server), and network errors
 * 
 * Usage:
 *   import { fetchLeads, approveLead } from './services/api';
 *   const leads = await fetchLeads({ industry: 'healthcare', min_score: 75 });
 */

// Configuration
const BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8001';
const REQUEST_TIMEOUT = 30000;       // 30 seconds — default
const CHAT_TIMEOUT    = 180000;      // 3 minutes — Scout + Analyst can take a while

/**
 * Fetch wrapper with error handling, timeout, and logging.
 * @param {string} endpoint - API endpoint path (e.g., '/leads')
 * @param {object} options - fetch options (method, body, headers, etc.)
 * @returns {Promise<any>} - Parsed response data
 */
async function fetchAPI(endpoint, options = {}) {
  const url = `${BASE_URL}${endpoint}`;
  const defaultHeaders = {
    'Content-Type': 'application/json',
    ...options.headers,
  };

  const timeout = options.timeout || REQUEST_TIMEOUT;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  try {
    const response = await fetch(url, {
      ...options,
      headers: defaultHeaders,
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    // Handle specific status codes
    if (response.status === 401) {
      console.warn('API authentication failed');
    }
    if (response.status === 500) {
      console.error('Server error — check API logs');
    }

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    const data = await response.json();
    return data;
  } catch (error) {
    clearTimeout(timeoutId);

    if (error.name === 'AbortError') {
      console.error(`Request timeout after ${REQUEST_TIMEOUT}ms: ${endpoint}`);
    } else if (error instanceof TypeError) {
      console.error('Cannot reach API server — check docker-compose is running');
    } else {
      console.error(`API error: ${error.message}`);
    }

    throw error;
  }
}

/**
 * Utility: Build query string from object
 * @param {object} params - Query parameters
 * @returns {string} - URL query string
 */
function buildQueryString(params) {
  const filtered = Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')
  );
  const searchParams = new URLSearchParams(filtered);
  return searchParams.toString();
}

// ============================================================================
// LEAD MANAGEMENT FUNCTIONS
// ============================================================================

/**
 * 1. Fetch leads with optional filters
 * @param {object} filters - { industry, state, tier, status, min_score, page, page_size }
 * @returns {Promise<object>} - LeadListResponse data
 */
export async function fetchLeads(filters = {}) {
  const query = buildQueryString(filters);
  const endpoint = query ? `/leads?${query}` : '/leads';
  return fetchAPI(endpoint);
}

/**
 * 2. Fetch a specific lead by company ID
 * @param {string} companyId - Company UUID
 * @returns {Promise<object>} - LeadResponse data
 */
export async function fetchLeadById(companyId) {
  return fetchAPI(`/leads/${companyId}`);
}

/**
 * 3. Fetch all high-tier leads
 * @returns {Promise<object>} - LeadListResponse data
 */
export async function fetchHighLeads() {
  return fetchAPI('/leads/high');
}

/**
 * 4. Approve a lead
 * @param {string} companyId - Company UUID
 * @param {string} approvedBy - Approver name
 * @returns {Promise<object>} - Success response
 */
export async function approveLead(companyId, approvedBy) {
  return fetchAPI(`/leads/${companyId}/approve`, {
    method: 'PATCH',
    body: JSON.stringify({ approved_by: approvedBy }),
  });
}

/**
 * 5. Reject a lead
 * @param {string} companyId - Company UUID
 * @param {string} rejectedBy - Rejecter name
 * @param {string} reason - Rejection reason
 * @returns {Promise<object>} - Success response
 */
export async function rejectLead(companyId, rejectedBy, reason) {
  return fetchAPI(`/leads/${companyId}/reject`, {
    method: 'PATCH',
    body: JSON.stringify({
      rejected_by: rejectedBy,
      rejection_reason: reason,
    }),
  });
}

// ============================================================================
// EMAIL MANAGEMENT FUNCTIONS
// ============================================================================

/**
 * 6. Fetch emails with optional filters
 * @param {object} filters - { page, page_size, approved_only }
 * @returns {Promise<object>} - EmailListResponse data
 */
export async function fetchEmails(filters = {}) {
  const query = buildQueryString(filters);
  const endpoint = query ? `/emails?${query}` : '/emails';
  return fetchAPI(endpoint);
}

/**
 * 7. Fetch only pending (unapproved) emails
 * @returns {Promise<object>} - EmailListResponse data
 */
export async function fetchPendingEmails() {
  return fetchAPI('/emails/pending');
}

/**
 * 8. Approve an email draft
 * @param {string} draftId - Draft UUID
 * @param {string} approvedBy - Approver name
 * @returns {Promise<object>} - Success response
 */
export async function approveEmail(draftId, approvedBy) {
  return fetchAPI(`/emails/${draftId}/approve`, {
    method: 'PATCH',
    body: JSON.stringify({ approved_by: approvedBy }),
  });
}

/**
 * 9. Edit an email draft
 * @param {string} draftId - Draft UUID
 * @param {string} editedBy - Editor name
 * @param {string} newSubject - New subject line (optional)
 * @param {string} newBody - New email body (optional)
 * @returns {Promise<object>} - Success response
 */
export async function editEmail(draftId, editedBy, newSubject, newBody) {
  const body = {
    edited_by: editedBy,
  };
  if (newSubject) body.new_subject_line = newSubject;
  if (newBody) body.new_body = newBody;

  return fetchAPI(`/emails/${draftId}/edit`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  });
}

/**
 * 10. Reject an email draft
 * @param {string} draftId - Draft UUID
 * @param {string} rejectedBy - Rejecter name
 * @param {string} reason - Rejection reason
 * @returns {Promise<object>} - Success response
 */
export async function rejectEmail(draftId, rejectedBy, reason) {
  return fetchAPI(`/emails/${draftId}/reject`, {
    method: 'PATCH',
    body: JSON.stringify({
      rejected_by: rejectedBy,
      rejection_reason: reason,
    }),
  });
}

/**
 * 11. Regenerate an email draft
 * @param {string} draftId - Draft UUID
 * @returns {Promise<object>} - New EmailDraftResponse
 */
export async function regenerateEmail(draftId) {
  return fetchAPI(`/emails/${draftId}/regenerate`, {
    method: 'POST',
  });
}

// ============================================================================
// PIPELINE MONITORING FUNCTIONS
// ============================================================================

/**
 * 12. Fetch current pipeline status
 * @returns {Promise<object>} - PipelineStatusResponse
 */
export async function fetchPipelineStatus() {
  return fetchAPI('/pipeline/status');
}

/**
 * 13. Fetch agent health metrics
 * @returns {Promise<object>} - AgentHealthResponse
 */
export async function fetchAgentHealth() {
  return fetchAPI('/pipeline/health');
}

/**
 * 14. Fetch recent pipeline activity
 * @param {number} limit - Number of recent events (default 10)
 * @returns {Promise<object>} - RecentActivityResponse
 */
export async function fetchRecentActivity(limit = 10) {
  return fetchAPI(`/pipeline/activity?limit=${limit}`);
}

// ============================================================================
// TRIGGER FUNCTIONS
// ============================================================================

/**
 * 15. Trigger full pipeline run
 * @param {string} industry - Target industry
 * @param {string} location - Target location
 * @param {number} count - Number of leads to find
 * @returns {Promise<object>} - TriggerResponse
 */
export async function triggerFullPipeline(industry, location, count) {
  return fetchAPI('/trigger/full', {
    method: 'POST',
    body: JSON.stringify({
      industry,
      location,
      count,
      run_mode: 'full',
    }),
  });
}

/**
 * 16. Trigger scout stage only
 * @param {string} industry - Target industry
 * @param {string} location - Target location
 * @param {number} count - Number of companies to find
 * @returns {Promise<object>} - TriggerResponse
 */
export async function triggerScout(industry, location, count) {
  return fetchAPI('/trigger/scout', {
    method: 'POST',
    body: JSON.stringify({
      industry,
      location,
      count,
      run_mode: 'scout_only',
    }),
  });
}

/**
 * 19. Fetch trigger execution status
 * @param {string} triggerId - Trigger UUID
 * @returns {Promise<object>} - TriggerStatusResponse
 */
export async function fetchTriggerStatus(triggerId) {
  return fetchAPI(`/trigger/${triggerId}/status`);
}

// ============================================================================
// REPORTING FUNCTIONS
// ============================================================================

/**
 * 17. Fetch weekly report
 * @param {string} startDate - Start date (optional, ISO format)
 * @param {string} endDate - End date (optional, ISO format)
 * @returns {Promise<object>} - WeeklyReportResponse
 */
export async function fetchWeeklyReport(startDate, endDate) {
  const params = {};
  if (startDate) params.start_date = startDate;
  if (endDate) params.end_date = endDate;
  const query = buildQueryString(params);
  const endpoint = query ? `/reports/weekly?${query}` : '/reports/weekly';
  return fetchAPI(endpoint);
}

/**
 * 18. Fetch top performing leads
 * @param {number} limit - Number of top leads (default 10)
 * @returns {Promise<object>} - TopLeadsResponse
 */
export async function fetchTopLeads(limit = 10) {
  return fetchAPI(`/reports/top-leads?limit=${limit}`);
}

// ============================================================================
// CHAT AGENT FUNCTIONS
// ============================================================================

/**
 * Start a chat run in the background — returns run_id immediately.
 * The client should then poll fetchRunStatus + fetchChatResult.
 * @param {string} message - User message
 * @returns {Promise<object>} - { run_id, status: "started" }
 */
export async function startChat(message) {
  return fetchAPI('/chat', {
    method: 'POST',
    body: JSON.stringify({ message }),
  });
}

/**
 * Poll for the result of a background chat run.
 * @param {string} runId - run_id returned by startChat
 * @returns {Promise<object>} - { status: "pending"|"done"|"error", reply, data, run_id }
 */
export async function fetchChatResult(runId) {
  return fetchAPI(`/chat/result/${runId}`);
}

// ============================================================================
// RUN STATUS FUNCTION
// ============================================================================

/**
 * Poll the status of an agent run by run_id.
 * @param {string} runId - AgentRun UUID
 * @returns {Promise<object>} - run status and counters
 */
export async function fetchRunStatus(runId) {
  return fetchAPI(`/pipeline/run/${runId}`);
}

// ============================================================================
// HEALTH CHECK FUNCTION
// ============================================================================

/**
 * 20. Check API server health
 * @returns {Promise<object>} - Health check response
 */
export async function checkApiHealth() {
  return fetchAPI('/health');
}
