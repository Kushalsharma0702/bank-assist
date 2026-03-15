import React, { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import './ConversationBot.css';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000' || 'https://eb5c-2401-4900-8841-f341-d3d-3ff0-7b6b-1e04.ngrok-free.app';
const WS_BASE_URL = API_BASE_URL
  .replace(/^https?/, p => p === 'https' ? 'wss' : 'ws');

const DEFAULT_LANGUAGES = {
  'km-KH': { name: 'Khmer', flag: '🇰🇭' },
  'en-US': { name: 'English', flag: '🇺🇸' },
};

const INTENT_COLOR = {
  GREETING:'green', BALANCE:'blue', STATEMENT:'blue', CARD_BLOCK:'red',
  TX_DISPUTE:'red', KYC_STATUS:'amber', EMI_DUE:'amber', FORECLOSURE:'purple',
  ADDRESS_CHANGE:'teal', COLLECTIONS_PTP:'orange', COLLECTIONS_PAYLINK:'orange',
  PAYMENT_DIFFICULTY:'red', CALLBACK:'teal', REQUEST_AGENT:'purple',
  THANKS:'green', PARTIAL_PAYMENT:'amber', FULL_PAYMENT:'green', UNKNOWN:'gray',
};

// ── Audio queue for sequential WAV playback ──────────────────────────────────
class AudioQueue {
  constructor(onStart, onEnd) {
    this._q = [];
    this._playing = false;
    this._current = null;  // current Audio element
    this.onStart = onStart;
    this.onEnd = onEnd;
  }
  enqueue(wavBytes) {
    const blob = new Blob([wavBytes], { type: 'audio/wav' });
    const url  = URL.createObjectURL(blob);
    this._q.push(url);
    if (!this._playing) this._playNext();
  }
  // ── Barge-in: stop current audio and clear queue immediately ──
  stopNow() {
    if (this._current) {
      this._current.pause();
      this._current.src = '';
      this._current = null;
    }
    // Revoke all queued blobs
    this._q.forEach(url => { try { URL.revokeObjectURL(url); } catch {} });
    this._q = [];
    this._playing = false;
    this.onEnd?.(true);   // true = force-stopped (do NOT send playback_done)
  }
  _playNext() {
    if (!this._q.length) { this._playing = false; this.onEnd?.(false); return; }
    this._playing = true;
    this.onStart?.();
    const url = this._q.shift();
    const audio = new Audio(url);
    this._current = audio;
    audio.onended = () => { this._current = null; URL.revokeObjectURL(url); this._playNext(); };
    audio.onerror = () => { this._current = null; URL.revokeObjectURL(url); this._playNext(); };
    audio.play().catch(() => this._playNext());
  }
  clear() { this.stopNow(); }
}

// ── Mic capture → PCM Int16 at 16 kHz via ScriptProcessor ───────────────────
async function openMicStream(onPcmChunk) {
  // Request hardware-level echo cancellation and noise suppression.
  // This removes the bot's TTS audio (played via speaker) from the mic
  // signal BEFORE it reaches our PCM pipeline, eliminating the doubled-word
  // duplication in Azure STT transcripts.  autoGainControl is intentionally
  // off — AGC can amplify residual echo and make AEC harder.
  const stream  = await navigator.mediaDevices.getUserMedia({
    audio: {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl:  true,   // keeps mic level consistent for barge-in detection
      sampleRate:       { ideal: 16000 },
      channelCount:     { ideal: 1 },
    },
  });
  const ctx     = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
  if (ctx.state === 'suspended') {
    try { await ctx.resume(); } catch {}
  }
  const source  = ctx.createMediaStreamSource(stream);
  const proc    = ctx.createScriptProcessor(4096, 1, 1);
  proc.onaudioprocess = e => {
    const f32 = e.inputBuffer.getChannelData(0);
    const i16 = new Int16Array(f32.length);
    for (let i = 0; i < f32.length; i++)
      i16[i] = Math.max(-32768, Math.min(32767, Math.round(f32[i] * 32767)));
    onPcmChunk(i16.buffer);
  };
  // Route source → proc → silent sink → destination.
  // The silent sink (gain = 0) keeps onaudioprocess alive in all browsers
  // WITHOUT playing the mic audio back through the speakers — a second echo
  // source that would defeat the hardware AEC above.
  const sink = ctx.createGain();
  sink.gain.value = 0;
  source.connect(proc);
  proc.connect(sink);
  sink.connect(ctx.destination);
  return { stream, ctx, proc, source, sink };
}

function closeMicStream(micRef) {
  if (!micRef) return;
  try { micRef.proc?.disconnect(); micRef.source?.disconnect(); micRef.sink?.disconnect(); } catch {}
  try { micRef.stream?.getTracks().forEach(t => t.stop()); } catch {}
  try { micRef.ctx?.close(); } catch {}
}

// ── Wave animation bars ───────────────────────────────────────────────────────
const WaveBars = ({ active, color = '#34d399', count = 12 }) => (
  <div className="cb-wave-bars">
    {Array.from({ length: count }, (_, i) => (
      <span
        key={i}
        className={`cb-wave-bar ${active ? 'cb-wave-bar--active' : ''}`}
        style={{ '--delay': `${i * 0.06}s`, '--color': color }}
      />
    ))}
  </div>
);

// ── Chat message bubble ───────────────────────────────────────────────────────
const Bubble = ({ msg }) => {
  const isUser = msg.role === 'user';
  const isSys  = msg.role === 'system';
  return (
    <div className={`cb-bubble cb-bubble--${isUser ? 'user' : isSys ? 'sys' : 'bot'}`}>
      {!isSys && (
        <div className="cb-bubble-avatar">{isUser ? '👤' : '🤖'}</div>
      )}
      <div className="cb-bubble-body">
        {msg.intent && (
          <span className={`cb-intent-chip cb-intent-chip--${INTENT_COLOR[msg.intent] || 'gray'}`}>
            {msg.intent}
          </span>
        )}
        <p className={msg.isKhmer ? 'kh-font' : ''}>{msg.text}</p>
        {msg.time && <span className="cb-bubble-time">{msg.time}</span>}
      </div>
    </div>
  );
};

// ── Status pill ───────────────────────────────────────────────────────────────
const STATUS_CFG = {
  idle:        { label: 'Ready',          color: '#64748b', icon: '💤' },
  connecting:  { label: 'Connecting…',   color: '#f59e0b', icon: '🔗' },
  greeting:    { label: 'Maya speaking…',color: '#10b981', icon: '🔊' },
  listening:   { label: 'Listening…',    color: '#06b6d4', icon: '🎤' },
  processing:  { label: 'Processing…',   color: '#8b5cf6', icon: '✨' },
  speaking:    { label: 'Maya speaking…',color: '#10b981', icon: '🔊' },
  ended:       { label: 'Call ended',    color: '#64748b', icon: '📵' },
  error:       { label: 'Error',         color: '#ef4444', icon: '⚠️' },
};

// ═══════════════════════════════════════════════════════════════════════════
//  Main ConversationBot component
// ═══════════════════════════════════════════════════════════════════════════

export const ConversationBot = ({ mode = 'conversation' }) => {
  // mode: 'conversation' → /ws/conversation (turn-based)
  //       'duplex'       → /ws/duplex (true-duplex barge-in)
  const [callState,    setCallState]    = useState('idle'); // idle|connecting|greeting|listening|processing|speaking|ended
  const [language,     setLanguage]     = useState('km-KH'); // STT / input
  const [outputLang,   setOutputLang]   = useState('km-KH'); // TTS / output
  const [region,       setRegion]       = useState('Others'); // engine routing
  const [messages,     setMessages]     = useState([]);
  const [languages,    setLanguages]    = useState(DEFAULT_LANGUAGES);
  const [partial,      setPartial]      = useState('');
  const [botToken,     setBotToken]     = useState('');
  const [isBotSpeaking,setIsBotSpeaking]= useState(false);
  const [currentIntent,setCurrentIntent]= useState(null);
  const currentIntentRef = useRef(null);
  const [callDuration, setCallDuration] = useState(0);
  const [error,        setError]        = useState('');
  const [bargeIn,      setBargeIn]      = useState(false);  // flash on barge-in
  const [transcripts,  setTranscripts]  = useState([]);

  const filteredLanguages = useMemo(() => {
    if (region === 'India') {
      return Object.fromEntries(
        Object.entries(languages).filter(([code]) => code.endsWith('-IN') || code === 'bn-BD')
      );
    }
    return languages;
  }, [languages, region]);

  useEffect(() => {
    if (Object.keys(filteredLanguages).length > 0) {
      if (!filteredLanguages[language]) setLanguage(Object.keys(filteredLanguages)[0]);
      if (!filteredLanguages[outputLang]) setOutputLang(Object.keys(filteredLanguages)[0]);
    }
  }, [filteredLanguages, language, outputLang]);

  const wsRef        = useRef(null);
  const micRef       = useRef(null);
  const micWatchdogRef = useRef(null);
  const audioQRef    = useRef(null);
  const chatEndRef   = useRef(null);
  const timerRef     = useRef(null);
  const callStartRef = useRef(null);
  // Refs so startCall always reads the latest language values (avoids stale closure)
  const langRef      = useRef(language);
  const outputLangRef= useRef(outputLang);
  const regionRef    = useRef(region);

  // Keep language refs in sync with state
  useEffect(() => { langRef.current = language; }, [language]);
  useEffect(() => { outputLangRef.current = outputLang; }, [outputLang]);
  useEffect(() => { regionRef.current = region; }, [region]);

  // Auto-scroll chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, partial, botToken]);

  // Call duration timer
  useEffect(() => {
    if (callState === 'listening' || callState === 'speaking' || callState === 'processing' || callState === 'greeting') {
      if (!timerRef.current) {
        callStartRef.current = callStartRef.current || Date.now();
        timerRef.current = setInterval(() => {
          setCallDuration(Math.floor((Date.now() - callStartRef.current) / 1000));
        }, 1000);
      }
    } else {
      clearInterval(timerRef.current);
      timerRef.current = null;
      if (callState === 'idle') {
        setCallDuration(0);
        callStartRef.current = null;
      }
    }
    return () => {};
  }, [callState]);

  const addMsg = useCallback((role, text, extra = {}) => {
    setMessages(prev => [...prev, {
      id: Date.now() + Math.random(),
      role, text,
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      ...extra,
    }]);
  }, []);

  const formatDuration = s => {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}:${sec.toString().padStart(2, '0')}`;
  };

  // ── Open mic and start streaming PCM to WS ─────────────────────────────────
  const startMic = useCallback(async () => {
    if (micRef.current) return;
    try {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      micRef.current = await openMicStream(pcm => {
        if (ws.readyState === WebSocket.OPEN) ws.send(pcm);
      });
      micRef.current.ctx.onstatechange = () => {
        if (mode === 'duplex' && micRef.current?.ctx?.state === 'suspended') {
          micRef.current.ctx.resume().catch(() => {});
        }
      };
    } catch (e) {
      setError(`Mic error: ${e.message}`);
    }
  }, [mode]);

  const stopMic = useCallback(() => {
    closeMicStream(micRef.current);
    micRef.current = null;
  }, []);

  const ensureDuplexMicAlive = useCallback(() => {
    if (mode !== 'duplex') return;
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    if (!micRef.current) {
      startMic();
      return;
    }
    if (micRef.current.ctx?.state === 'suspended') {
      micRef.current.ctx.resume().catch(() => {});
    }
  }, [mode, startMic]);

  // ── Handle WebSocket messages ──────────────────────────────────────────────
  const handleWsMessage = useCallback((evt) => {
    if (evt.data instanceof ArrayBuffer || evt.data instanceof Blob) {
      // Binary: WAV audio chunk
      const toBuffer = evt.data instanceof Blob
        ? evt.data.arrayBuffer()
        : Promise.resolve(evt.data);
      toBuffer.then(buf => audioQRef.current?.enqueue(buf));
      return;
    }

    let msg;
    try { msg = JSON.parse(evt.data); }
    catch { return; }

    switch (msg.type) {
      case 'state':
        setCallState(msg.state);
        if (msg.state === 'listening') {
          setPartial('');
          setBotToken('');
          startMic();  // always start mic when listening
        } else if (mode === 'duplex') {
          // DUPLEX: keep mic on always (for barge-in detection)
          startMic();
          if (msg.state === 'processing' || msg.state === 'speaking' || msg.state === 'greeting') {
            setPartial('');
          }
        } else {
          // TURN-BASED: stop mic during bot response
          if (msg.state === 'processing' || msg.state === 'speaking' || msg.state === 'greeting') {
            stopMic();
            setPartial('');
          }
        }
        break;

      // ── Duplex wire protocol names ──
      case 'partial':                     // duplex sends 'partial'
      case 'partial_transcript':          // conversation sends 'partial_transcript'
        setPartial(msg.text);
        break;

      case 'final':                       // duplex sends 'final'
      case 'final_transcript':            // conversation sends 'final_transcript'
        setPartial('');
        addMsg('user', msg.text);
        setTranscripts(prev => ([
          ...prev,
          {
            id: Date.now() + Math.random(),
            text: msg.text,
            englishText: msg.english_text || msg.text,
            outputText: msg.output_text || msg.text,
            outputLanguage: msg.output_language || outputLangRef.current,
            time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          },
        ]));
        break;

      case 'token':                       // duplex sends 'token'
      case 'bot_text_token':              // conversation sends 'bot_text_token'
        setBotToken(prev => prev + msg.text);
        break;

      case 'bot_sentence':
      case 'sentence':                    // duplex sends 'sentence'
        // Sentence being synthesised (informational)
        break;

      case 'intent':
        setCurrentIntent(msg.intent);
        currentIntentRef.current = msg.intent;
        break;

      case 'turn_end':                   // duplex sends 'turn_end'
      case 'turn_complete':               // conversation sends 'turn_complete'
        // Commit accumulated bot tokens as a message
        setBotToken(prev => {
          if (prev.trim()) addMsg('bot', prev.trim(), { intent: currentIntentRef.current });
          return '';
        });
        setCurrentIntent(null);
        currentIntentRef.current = null;
        break;

      case 'ended':
        stopMic();
        audioQRef.current?.clear();
        const reason = msg.reason || 'ended';
        const endText = reason === 'hangup' || reason === 'user_hangup'
          ? 'Call ended by you.'
          : reason.startsWith('resolved')
          ? '✅ Your query has been resolved. Call ended.'
          : 'Call ended.';
        addMsg('system', endText);
        setCallState('ended');
        break;

      case 'tts_stop':
        // Server barge-in: stop audio immediately, flash indicator
        audioQRef.current?.stopNow();
        setIsBotSpeaking(false);
        setBargeIn(true);
        setTimeout(() => setBargeIn(false), 600);
        break;

      case 'error':
        setError(msg.message);
        addMsg('system', `⚠️ ${msg.message}`);
        break;

      case 'language_change':
        if (msg.language) {
          setLanguage(msg.language);
          setOutputLang(msg.language);
        }
        break;

      default:
        break;
    }
  }, [addMsg, startMic, stopMic, currentIntent]);

  // ── Start a call ───────────────────────────────────────────────────────────
  const startCall = useCallback(() => {
    setError('');
    setMessages([]);
    setPartial('');
    setBotToken('');
    setTranscripts([]);
    setCurrentIntent(null);
    setCallState('connecting');
    callStartRef.current = Date.now();

    // Set up audio queue
    audioQRef.current = new AudioQueue(
      () => setIsBotSpeaking(true),
      (stopped) => {
        setIsBotSpeaking(false);
        // Notify backend that the browser has finished playing all audio so
        // the barge-in watch can be released cleanly.  Skip this when
        // stopNow() was called (barge-in already handled on backend).
        if (!stopped) {
          wsRef.current?.send(JSON.stringify({ type: 'playback_done' }));
        }
      },
    );

    // Read the LATEST language values from refs — avoids stale closure
    const inputLang = langRef.current;
    const outLang   = outputLangRef.current;
    const regionValue = regionRef.current;
    const wsPath    = mode === 'duplex' ? '/ws/duplex' : '/ws/conversation';
    const qs = new URLSearchParams({
      language: inputLang,
      output_language: outLang,
      region: regionValue,
    });

    const ws = new WebSocket(
      `${WS_BASE_URL}${wsPath}?${qs.toString()}`
    );
    ws.binaryType = 'arraybuffer';
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ type: 'start' }));
      if (mode === 'duplex') {
        startMic();
        setTimeout(() => startMic(), 250);
      }
    };
    ws.onmessage = handleWsMessage;
    ws.onerror = () => {
      setError('WebSocket connection failed.');
      setCallState('error');
    };
    ws.onclose = () => {
      stopMic();
      if (callState !== 'ended') setCallState('ended');
    };
  }, [handleWsMessage, stopMic, callState, mode, startMic]);

  // ── Hang up ────────────────────────────────────────────────────────────────
  const hangUp = useCallback(() => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'hangup' }));
      setTimeout(() => ws.close(), 500);
    }
    stopMic();
    audioQRef.current?.clear();
    setCallState('ended');
    addMsg('system', 'Call ended by you.');
  }, [stopMic, addMsg]);

  // ── Reset ──────────────────────────────────────────────────────────────────
  const resetCall = useCallback(() => {
    wsRef.current?.close();
    stopMic();
    audioQRef.current?.clear();
    setMessages([]);
    setPartial('');
    setBotToken('');
    setTranscripts([]);
    setCallState('idle');
    setError('');
    setCallDuration(0);
    callStartRef.current = null;
  }, [stopMic]);

  // Load languages from backend so dropdowns stay in sync with server support.
  useEffect(() => {
    let isMounted = true;
    const loadLanguages = async () => {
      try {
        const resp = await fetch(`${API_BASE_URL}/languages`);
        if (!resp.ok) return;
        const data = await resp.json();
        if (!isMounted || !data || typeof data !== 'object') return;
        setLanguages(prev => ({ ...prev, ...data }));
        if (!data[language]) {
          const first = Object.keys(data)[0];
          if (first) setLanguage(first);
        }
        if (!data[outputLang]) {
          const first = Object.keys(data)[0];
          if (first) setOutputLang(first);
        }
      } catch {
        // Keep default fallback list.
      }
    };
    loadLanguages();
    return () => { isMounted = false; };
  }, []);

  useEffect(() => {
    clearInterval(micWatchdogRef.current);
    micWatchdogRef.current = null;
    if (mode !== 'duplex') return () => {};
    if (!['connecting', 'greeting', 'listening', 'processing', 'speaking'].includes(callState)) {
      return () => {};
    }
    micWatchdogRef.current = setInterval(() => {
      ensureDuplexMicAlive();
    }, 1500);
    return () => {
      clearInterval(micWatchdogRef.current);
      micWatchdogRef.current = null;
    };
  }, [mode, callState, ensureDuplexMicAlive]);

  // Cleanup on unmount
  useEffect(() => () => {
    wsRef.current?.close();
    stopMic();
    clearInterval(micWatchdogRef.current);
    clearInterval(timerRef.current);
  }, [stopMic]);

  const isActive = ['connecting','greeting','listening','processing','speaking'].includes(callState);
  const statusCfg = STATUS_CFG[callState] || STATUS_CFG.idle;

  return (
    <div className="cb-root">
      {/* ── Header ── */}
      <header className="cb-header">
        <div className="cb-header-badge">
          {mode === 'duplex' ? '⚡ DUPLEX BARGE-IN' : 'LIVE CONVERSATION'}
        </div>
        <h1>Intalks AI Banking Assistant</h1>
        <p>Real-time voice banking · Live transcript · Instant barge-in</p>
      </header>

      <div className="cb-layout">

        {/* ── Left panel: call controls ── */}
        <aside className="cb-sidebar">

          {/* Avatar orb */}
          <div className="cb-avatar-area">
            <div className={`cb-avatar cb-avatar--${callState}`}>
              <div className="cb-avatar-ring cb-ring--1" />
              <div className="cb-avatar-ring cb-ring--2" />
              <div className="cb-avatar-ring cb-ring--3" />
              <div className="cb-avatar-face">
                <span className="cb-avatar-emoji">
                  {callState === 'listening' ? '🎤' :
                   callState === 'processing' ? '✨' :
                   (callState === 'speaking' || callState === 'greeting') ? '🔊' :
                   callState === 'ended' ? '📵' : '🤖'}
                </span>
              </div>
            </div>
            <div className="cb-avatar-name">Maya</div>
            <div className="cb-avatar-role">Banking AI Assistant</div>
          </div>

          {/* Status pill */}
          <div className="cb-status-pill" style={{ '--status-color': statusCfg.color }}>
            <span className="cb-status-dot" />
            <span>{statusCfg.icon} {statusCfg.label}</span>
          </div>

          {/* Call timer */}
          {isActive && (
            <div className="cb-timer">
              <span className="cb-timer-dot" />
              {formatDuration(callDuration)}
            </div>
          )}

          {/* Wave bars */}
          <div className="cb-wave-section">
            {callState === 'listening' && (
              <WaveBars active color="#06b6d4" count={14} />
            )}
            {(callState === 'speaking' || callState === 'greeting') && (
              <WaveBars active={isBotSpeaking} color="#10b981" count={14} />
            )}
            {callState === 'processing' && (
              <div className="cb-processing-dots">
                <span /><span /><span />
              </div>
            )}
          </div>

          {/* Language selectors */}
          {!isActive && callState !== 'ended' && (
            <div className="cb-lang-section">
              <label>🎤 Input language (you speak)</label>
              <select value={language} onChange={e => setLanguage(e.target.value)}>
                {Object.entries(filteredLanguages).map(([code, cfg]) => (
                  <option key={code} value={code}>{cfg.flag} {cfg.name}</option>
                ))}
              </select>
              <label style={{ marginTop: 10 }}>🔊 Output language (Maya speaks)</label>
              <select value={outputLang} onChange={e => setOutputLang(e.target.value)}>
                {Object.entries(filteredLanguages).map(([code, cfg]) => (
                  <option key={code} value={code}>{cfg.flag} {cfg.name}</option>
                ))}
              </select>
              <label style={{ marginTop: 10 }}>🌍 Region engine</label>
              <select value={region} onChange={e => setRegion(e.target.value)}>
                <option value="Others">Others</option>
                <option value="India">India</option>
              </select>
            </div>
          )}

          {/* Call / Hang-up buttons */}
          <div className="cb-btn-area">
            {callState === 'idle' && (
              <button id="cb-start-btn" className="cb-btn cb-btn--call" onClick={startCall}>
                📞 Start Call
              </button>
            )}
            {isActive && (
              <button id="cb-hangup-btn" className="cb-btn cb-btn--hangup" onClick={hangUp}>
                📵 Hang Up
              </button>
            )}
            {callState === 'ended' && (
              <>
                <button id="cb-recall-btn" className="cb-btn cb-btn--call" onClick={startCall}>
                  📞 Call Again
                </button>
                <button className="cb-btn cb-btn--secondary" onClick={resetCall}>
                  🗑 Clear
                </button>
              </>
            )}
          </div>

          {/* Error */}
          {error && (
            <div className="cb-error">⚠️ {error}</div>
          )}

          {/* How it works */}
          <div className="cb-info-card">
            <div className="cb-info-title">
              {mode === 'duplex' ? 'Duplex Mode' : 'How it works'}
            </div>
            <ul className="cb-info-list">
              {mode === 'duplex' ? (
                <>
                  <li>⚡ <strong>Interrupt anytime</strong> — speak while Maya talks</li>
                  <li>🎤 Mic stays on during bot speech (always listening)</li>
                  <li>🔇 Maya stops instantly on barge-in</li>
                  <li>🧠 Your new query is processed immediately</li>
                  <li>📵 Say "bye" or tap <em>Hang Up</em></li>
                </>
              ) : (
                <>
                  <li>🟢 <strong>Start Call</strong> — Maya greets you</li>
                  <li>🎤 Just speak naturally</li>
                  <li>⏸ Stop speaking → Maya responds</li>
                  <li>🔁 Conversation continues until resolved</li>
                  <li>📵 Say "bye" or tap <em>Hang Up</em></li>
                </>
              )}
            </ul>
          </div>
        </aside>

        {/* ── Main: conversation ── */}
        <main className="cb-chat-panel">

          {/* Header bar */}
          <div className="cb-chat-header">
            <div className="cb-chat-header-info">
              <div className="cb-chat-avatar-mini">🤖</div>
              <div>
                <div className="cb-chat-title">Maya</div>
                <div className="cb-chat-sub">
                  {isActive ? `Active · ${formatDuration(callDuration)}` : 'Intalks AI Banking Assistant'}
                </div>
              </div>
            </div>
            <div className="cb-chat-status" style={{ '--status-color': statusCfg.color }}>
              <span className="cb-status-dot-sm" />
              {statusCfg.label}
            </div>
          </div>

          {/* Transcript board */}
          <div className="cb-transcript-board">
            <div className="cb-transcript-head">
              <div className="cb-transcript-title">📝 Live Transcript</div>
              <div className="cb-transcript-meta">
                {transcripts.length} turns captured
              </div>
            </div>

            <div className={`cb-transcript-live ${partial ? 'cb-transcript-live--active' : ''}`}>
              <span className="cb-transcript-live-label">Now hearing</span>
              <p>
                {partial || 'Waiting for speech...'}
                {partial && <span className="cb-cursor" />}
              </p>
            </div>

            <div className="cb-transcript-list">
              {transcripts.length === 0 && (
                <div className="cb-transcript-empty">No finalized transcript yet.</div>
              )}
              {transcripts.slice(-4).reverse().map(item => {
                const outputName = languages[item.outputLanguage]?.name || 'Selected language';
                const isOutputKhmer = item.outputLanguage === 'km-KH';
                return (
                  <div key={item.id} className="cb-transcript-item">
                    <div className="cb-transcript-item-top">
                      <span className="cb-transcript-chip">Customer</span>
                      <span className="cb-transcript-time">{item.time}</span>
                    </div>
                    <span className="cb-transcript-line-label">{outputName}</span>
                    <p className={isOutputKhmer ? 'kh-font' : ''}>{item.outputText || item.text}</p>
                    <span className="cb-transcript-line-label cb-transcript-line-label--english">English</span>
                    <p>{item.englishText || item.text}</p>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Messages */}
          <div className="cb-messages">
            {messages.length === 0 && callState === 'idle' && (
              <div className="cb-empty">
                <div className="cb-empty-icon">📞</div>
                <p className="cb-empty-title">Start a conversation</p>
                <p className="cb-empty-sub">
                  Press <strong>Start Call</strong> to begin a live voice conversation with Maya.
                  She will greet you and listen to your banking query.
                </p>
                <div className="cb-features">
                  {[
                    ['🎤', 'Auto voice detection'],
                    ['🔄', 'Bidirectional turns'],
                    ['🌐', 'Multilingual'],
                    ['🤖', 'Claude AI powered'],
                  ].map(([icon, label]) => (
                    <div key={label} className="cb-feature-chip">
                      <span>{icon}</span> {label}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {messages.map(m => <Bubble key={m.id} msg={m} />)}

            {/* Live partial transcript */}
            {partial && (
              <div className="cb-bubble cb-bubble--user cb-bubble--partial">
                <div className="cb-bubble-avatar">👤</div>
                <div className="cb-bubble-body">
                  <p>{partial}<span className="cb-cursor" /></p>
                </div>
              </div>
            )}

            {/* Streaming bot tokens */}
            {botToken && (
              <div className="cb-bubble cb-bubble--bot cb-bubble--partial">
                <div className="cb-bubble-avatar">🤖</div>
                <div className="cb-bubble-body">
                  {currentIntent && (
                    <span className={`cb-intent-chip cb-intent-chip--${INTENT_COLOR[currentIntent] || 'gray'}`}>
                      {currentIntent}
                    </span>
                  )}
                  <p>{botToken}<span className="cb-cursor" /></p>
                </div>
              </div>
            )}

            <div ref={chatEndRef} />
          </div>

          {/* Bottom status bar */}
          <div className="cb-chat-footer">
            {callState === 'listening' && (
              <div className="cb-footer-listening">
                <span className="cb-mic-pulse" />
                Listening — speak naturally, then pause…
              </div>
            )}
            {callState === 'processing' && (
              <div className="cb-footer-processing">
                <div className="cb-spinner" /> Processing your message…
              </div>
            )}
            {(callState === 'speaking' || callState === 'greeting') && (
              <div className="cb-footer-speaking">
                <WaveBars active={isBotSpeaking} color="#10b981" count={8} />
                {bargeIn
                  ? '⚡ Barge-in! Stopping Maya…'
                  : mode === 'duplex'
                    ? 'Maya is responding… (speak to interrupt)'
                    : 'Maya is responding…'}
              </div>
            )}
            {(callState === 'idle' || callState === 'ended') && (
              <div className="cb-footer-idle">
                {callState === 'ended' ? '📵 Call ended' : '🎙 Tap Start Call to begin'}
              </div>
            )}
          </div>
        </main>
      </div>

      <footer className="cb-footer-bar" aria-label="Application footer">
        <span className="cb-footer-brand">Intalks AI Banking Assistant</span>
        <span className="cb-footer-sep">•</span>
        <span className="cb-footer-note">Secure voice support for modern banking</span>
      </footer>
    </div>
  );
};

export default ConversationBot;
