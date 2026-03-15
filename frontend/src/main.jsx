import React, { useState } from 'react';
import ReactDOM from 'react-dom/client';
import VoiceAssistant from './components/VoiceAssistant';
import ConversationBot from './components/ConversationBot';
import './index.css';

const TABS = [
  { id: 'duplex',       label: '⚡ Duplex Barge-In', desc: 'True duplex · Interrupt anytime',   color: '#059669' },
  { id: 'conversation', label: '📞 Turn-Based',       desc: 'Auto-VAD · No barge-in',            color: '#2563eb' },
  { id: 'single',       label: '🎙 Single Turn POC',  desc: 'Push-to-talk · Legacy',             color: '#7c3aed' },
];

const App = () => {
  const [tab, setTab] = useState('duplex');
  return (
    <>
      <div style={{
        position: 'fixed', top: 0, left: 0, right: 0, zIndex: 9999,
        display: 'flex', justifyContent: 'center', gap: '8px',
        padding: '10px 20px',
        background: 'rgba(9,13,26,0.92)',
        backdropFilter: 'blur(12px)',
        borderBottom: '1px solid rgba(255,255,255,0.1)',
        flexWrap: 'wrap',
      }}>
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            padding: '8px 20px', borderRadius: '99px', border: 'none', cursor: 'pointer',
            fontWeight: 700, fontSize: '0.82rem', letterSpacing: '0.3px',
            transition: 'all 0.2s',
            background: tab === t.id ? `linear-gradient(135deg,${t.color},${t.color}cc)` : 'rgba(255,255,255,0.07)',
            color: tab === t.id ? 'white' : 'rgba(241,245,249,0.6)',
            boxShadow: tab === t.id ? `0 4px 16px ${t.color}55` : 'none',
          }}>
            {t.label}
            <span style={{ display: 'block', fontSize: '0.62rem', fontWeight: 400, opacity: 0.75, letterSpacing: 0 }}>
              {t.desc}
            </span>
          </button>
        ))}
      </div>
      <div style={{ paddingTop: 68 }}>
        {tab === 'duplex'       && <ConversationBot mode="duplex" />}
        {tab === 'conversation' && <ConversationBot mode="conversation" />}
        {tab === 'single'       && <VoiceAssistant />}
      </div>
    </>
  );
};

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
