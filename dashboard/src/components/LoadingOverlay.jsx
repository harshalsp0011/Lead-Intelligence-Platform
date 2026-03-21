/**
 * LoadingOverlay
 *
 * Full-screen blur overlay shown while a page is fetching data.
 * Renders as a fixed layer above all content so the user knows something
 * is happening and cannot accidentally interact with stale data.
 *
 * Usage:
 *   {isLoading && <LoadingOverlay message="Loading leads..." />}
 */

import React from 'react';

export default function LoadingOverlay({ message = 'Loading...' }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center backdrop-blur-sm bg-white/50">
      <div className="bg-white rounded-2xl shadow-2xl px-10 py-8 flex flex-col items-center gap-4 border border-slate-100">
        {/* Spinner */}
        <div className="w-10 h-10 border-4 border-blue-600 border-t-transparent rounded-full animate-spin" />
        {/* Message */}
        <p className="text-slate-700 font-medium text-sm">{message}</p>
      </div>
    </div>
  );
}
