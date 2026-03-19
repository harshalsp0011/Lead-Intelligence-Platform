/**
 * PipelineStatusBar Component
 *
 * Shows the 5 agent stages with the currently active one highlighted.
 * Used in ScoutLive and Pipeline pages to show real-time run progress.
 *
 * Props:
 *   activeStage (string|null): one of 'scout'|'analyst'|'writer'|'outreach'|'tracker'|null
 *   counts (object): { companies_found, scored_high, scored_medium, contacts_found, drafts_created }
 *   status (string): 'idle'|'running'|'completed'|'failed'
 */

import React from 'react';

const STAGES = [
  { key: 'scout',    label: 'Scout',    icon: '🔍', desc: 'Finding companies' },
  { key: 'analyst',  label: 'Analyst',  icon: '📊', desc: 'Scoring leads' },
  { key: 'writer',   label: 'Writer',   icon: '✍️',  desc: 'Drafting emails' },
  { key: 'outreach', label: 'Outreach', icon: '📤', desc: 'Sending emails' },
  { key: 'tracker',  label: 'Tracker',  icon: '📬', desc: 'Monitoring replies' },
];

export default function PipelineStatusBar({ activeStage = null, counts = {}, status = 'idle' }) {
  const activeIdx = STAGES.findIndex((s) => s.key === activeStage);

  return (
    <div className="bg-white border border-slate-200 rounded-lg px-4 py-3">
      <div className="flex items-center gap-0">
        {STAGES.map((stage, idx) => {
          const isDone    = activeIdx >= 0 && idx < activeIdx;
          const isActive  = stage.key === activeStage;
          const isPending = activeIdx < 0 || idx > activeIdx;

          return (
            <React.Fragment key={stage.key}>
              {/* Stage pill */}
              <div className={`flex flex-col items-center px-3 py-1.5 rounded-lg transition-all ${
                isActive  ? 'bg-blue-600 text-white shadow-md'  :
                isDone    ? 'bg-green-100 text-green-700'       :
                            'text-slate-400'
              }`}>
                <span className="text-base leading-none">{stage.icon}</span>
                <span className={`text-xs font-semibold mt-0.5 ${isActive ? 'text-white' : ''}`}>
                  {stage.label}
                </span>
                {isActive && status === 'running' && (
                  <span className="text-xs text-blue-200 mt-0.5">{stage.desc}</span>
                )}
                {isDone && (
                  <span className="text-xs text-green-600 mt-0.5">Done</span>
                )}
              </div>

              {/* Arrow */}
              {idx < STAGES.length - 1 && (
                <div className={`flex-1 h-0.5 mx-1 ${
                  isDone ? 'bg-green-400' : 'bg-slate-200'
                }`} />
              )}
            </React.Fragment>
          );
        })}
      </div>

      {/* Counts row */}
      {(counts.companies_found > 0 || counts.scored_high > 0 || counts.drafts_created > 0) && (
        <div className="flex gap-4 mt-2 pt-2 border-t border-slate-100 text-xs text-slate-500">
          {counts.companies_found > 0 && (
            <span>Found: <strong className="text-slate-700">{counts.companies_found}</strong></span>
          )}
          {counts.scored_high > 0 && (
            <span>High: <strong className="text-green-700">{counts.scored_high}</strong></span>
          )}
          {counts.scored_medium > 0 && (
            <span>Medium: <strong className="text-yellow-700">{counts.scored_medium}</strong></span>
          )}
          {counts.contacts_found > 0 && (
            <span>Contacts: <strong className="text-slate-700">{counts.contacts_found}</strong></span>
          )}
          {counts.drafts_created > 0 && (
            <span>Drafts: <strong className="text-blue-700">{counts.drafts_created}</strong></span>
          )}
        </div>
      )}
    </div>
  );
}
