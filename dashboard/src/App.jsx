import React from 'react';
import { BrowserRouter, Routes, Route, NavLink, useLocation } from 'react-router-dom';

import Chat from './pages/Chat';
import Leads from './pages/Leads';
import ScoutLive from './pages/ScoutLive';
import EmailReview from './pages/EmailReview';
import Pipeline from './pages/Pipeline';
import Reports from './pages/Reports';

// ---------------------------------------------------------------------------
// Sidebar nav item
// ---------------------------------------------------------------------------
function NavItem({ to, icon, label }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-colors ${
          isActive
            ? 'bg-blue-600 text-white'
            : 'text-slate-300 hover:bg-slate-700 hover:text-white'
        }`
      }
    >
      <span className="text-lg">{icon}</span>
      <span>{label}</span>
    </NavLink>
  );
}

// ---------------------------------------------------------------------------
// Layout wrapper
// ---------------------------------------------------------------------------
function Layout({ children }) {
  return (
    <div className="flex h-screen bg-slate-50 overflow-hidden">
      {/* Sidebar */}
      <aside className="w-56 bg-slate-800 flex flex-col flex-shrink-0">
        {/* Brand */}
        <div className="px-4 py-5 border-b border-slate-700">
          <p className="text-white font-bold text-sm leading-tight">Troy & Banks</p>
          <p className="text-slate-400 text-xs mt-0.5">Lead Intelligence</p>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
          <NavItem to="/chat"     icon="💬" label="Chat Agent" />
          <NavItem to="/scout"    icon="🔍" label="Scout Live" />
          <NavItem to="/leads"    icon="📋" label="Leads" />
          <NavItem to="/emails"   icon="✉️"  label="Email Review" />
          <NavItem to="/pipeline" icon="⚙️"  label="Pipeline" />
          <NavItem to="/reports"  icon="📊" label="Reports" />
        </nav>

        {/* Footer */}
        <div className="px-4 py-3 border-t border-slate-700">
          <p className="text-slate-500 text-xs">Phase 1 — Local</p>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 flex flex-col overflow-hidden">
        {children}
      </main>
    </div>
  );
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------
export default function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/"         element={<Chat />} />
          <Route path="/chat"     element={<Chat />} />
          <Route path="/scout"    element={<ScoutLive />} />
          <Route path="/leads"    element={<Leads />} />
          <Route path="/emails"   element={<EmailReview />} />
          <Route path="/pipeline" element={<Pipeline />} />
          <Route path="/reports"  element={<Reports />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}
