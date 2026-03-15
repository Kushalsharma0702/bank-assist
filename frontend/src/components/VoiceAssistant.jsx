import React, {
  useState,
  useRef,
  useCallback,
  useEffect,
  useMemo,
} from 'react';
import axios from 'axios';
import './VoiceAssistant.css';
import InterruptionHandler from '../utils/InterruptionHandler';
import {
  initializeInterruptionHandler,
  setupTTSWithInterruption,
  getEnhancedAudioConstraints,
  createAudioLevelMonitor,
  getAudioErrorMessage,
} from '../utils/voiceAssistantEnhancements';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'|| 'https://eb5c-2401-4900-8841-f341-d3d-3ff0-7b6b-1e04.ngrok-free.app';

const DEFAULT_LANGUAGES = {
  'km-KH': { name: 'Khmer',              flag: '🇰🇭' },
  'en-US': { name: 'English',            flag: '🇺🇸' },
  'vi-VN': { name: 'Vietnamese',         flag: '🇻🇳' },
  'th-TH': { name: 'Thai',               flag: '🇹🇭' },
  'zh-CN': { name: 'Chinese (Mandarin)', flag: '🇨🇳' },
  'hi-IN': { name: 'Hindi',              flag: '🇮🇳' },
  'id-ID': { name: 'Indonesian',         flag: '🇮🇩' },
  'ms-MY': { name: 'Malay',             flag: '🇲🇾' },
};

// Stage metadata (must match orchestrator order)
const STAGE_META = [
  { key: 'STT',               label: 'Speech-to-Text',        icon: '🎤', color: 'stt'     },
  { key: 'Translation',       label: 'Translate → English',   icon: '🌐', color: 'trans'   },
  { key: 'Intent Detection',  label: 'Semantic Intent',       icon: '🎯', color: 'intent'  },
  { key: 'Workflow Engine',   label: 'Workflow Engine',       icon: '⚙️', color: 'wf'      },
  { key: 'AI Response',       label: 'AI Reasoning',          icon: '🤖', color: 'claude'  },
  { key: 'Native Translation',label: 'Translate → Customer',  icon: '🌏', color: 'ntrans'  },
  { key: 'TTS Audio',         label: 'Natural Voice Output',  icon: '🔊', color: 'tts'     },
];

const INTENT_COLOR = {
  GREETING:            'green',
  BALANCE:             'blue',
  STATEMENT:           'blue',
  CARD_BLOCK:          'red',
  TX_DISPUTE:          'red',
  KYC_STATUS:          'amber',
  EMI_DUE:             'amber',
  FORECLOSURE:         'purple',
  ADDRESS_CHANGE:      'teal',
  COLLECTIONS_PTP:     'orange',
  COLLECTIONS_PAYLINK: 'orange',
  PAYMENT_DIFFICULTY:  'red',
  CALLBACK:            'teal',
  REQUEST_AGENT:       'purple',
  THANKS:              'green',
  PARTIAL_PAYMENT:     'amber',
  FULL_PAYMENT:        'green',
  UNKNOWN:             'gray',
};

// ═══════════════════════════════════════════════════════════
//  PipelineVisualizer component
// ═══════════════════════════════════════════════════════════

const PipelineVisualizer = ({ stages, language }) => {
  const [visibleCount, setVisibleCount] = useState(0);

  useEffect(() => {
    if (!stages || stages.length === 0) { setVisibleCount(0); return; }
    setVisibleCount(0);
    let delay = 0;
    stages.forEach((_, i) => {
      const stageDelay = delay;
      setTimeout(() => setVisibleCount(i + 1), stageDelay);
      delay += Math.max(Math.min((stages[i]?.latency_ms || 300) * 0.35, 700), 200);
    });
  }, [stages]);

  if (!stages) return null;
  const isKhmer = language === 'km-KH';

  return (
    <div className="vp-root">
      <div className="vp-header">
        <span className="vp-header-label">AI Pipeline</span>
        <span className="vp-header-flow">
          STT → Translate → Intent → Workflow → Claude → Native → TTS
        </span>
      </div>
      <div className="vp-stages">
        {stages.map((stage, i) => {
          const meta  = STAGE_META[i] || { label: stage.name, icon: '●', color: 'default' };
          const shown = i < visibleCount;
          const isNativeOut = i === 5 || i === 6;

          return (
            <React.Fragment key={i}>
              <div className={`vp-stage vp-stage--${meta.color} ${shown ? 'vp-stage--visible' : ''} vp-stage--${stage.status}`}>
                {/* Left: badge */}
                <div className="vp-stage-badge">
                  <span className="vp-stage-icon">{meta.icon}</span>
                  <span className="vp-stage-num">{i + 1}</span>
                </div>

                {/* Center: content */}
                <div className="vp-stage-body">
                  <div className="vp-stage-title-row">
                    <span className="vp-stage-title">{meta.label}</span>
                    {stage.confidence != null && (
                      <span className="vp-stage-conf">
                        {(stage.confidence * 100).toFixed(0)}% conf.
                      </span>
                    )}
                  </div>
                  {stage.output && (
                    <p className={`vp-stage-output ${isNativeOut && isKhmer ? 'kh-font' : ''}`}>
                      {stage.output}
                    </p>
                  )}
                  {stage.matched_phrase && (
                    <p className="vp-stage-matched">
                      Matched: <em>"{stage.matched_phrase}"</em>
                    </p>
                  )}
                </div>

                {/* Right: latency */}
                <div className="vp-stage-right">
                  {stage.latency_ms != null && stage.latency_ms > 0 ? (
                    <span className="vp-latency">{Math.round(stage.latency_ms)} ms</span>
                  ) : stage.status === 'pending' ? (
                    <span className="vp-latency vp-latency--skip">skipped</span>
                  ) : null}
                  <span className={`vp-status-dot vp-status-dot--${stage.status}`} />
                </div>
              </div>

              {/* Connector arrow between stages */}
              {i < stages.length - 1 && (
                <div className={`vp-connector ${shown ? 'vp-connector--visible' : ''}`}>
                  <svg width="12" height="20" viewBox="0 0 12 20">
                    <line x1="6" y1="0" x2="6" y2="14" stroke="currentColor" strokeWidth="1.5" strokeDasharray="3 2"/>
                    <polygon points="2,12 6,20 10,12" fill="currentColor"/>
                  </svg>
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════
//  ResultCard component
// ═══════════════════════════════════════════════════════════

const ResultCard = ({ result, isSpeaking, onClose }) => {
  const intentColor = INTENT_COLOR[result.intent] || 'gray';
  const isKhmer     = result.language === 'km-KH';

  return (
    <div className="va-result-card">
      <div className="va-result-topbar">
        <h2>AI Response</h2>
        <button className="va-close-btn" onClick={onClose}>✕</button>
      </div>

      {/* Meta chips */}
      <div className="va-meta-row">
        <span className="va-chip va-chip--lang">
          {result.native_flag || '🌐'} {result.native_language_name}
        </span>
        {result.detected_language && result.detected_language !== result.language && (
          <span className="va-chip va-chip--detected" title="Language detected by Azure STT">
            STT detected: {result.detected_language}
          </span>
        )}
        <span className={`va-chip va-chip--intent va-chip--intent-${intentColor}`}>
          {result.intent}
        </span>
        {result.tts_voice && (
          <span className="va-chip va-chip--voice">🔊 {result.tts_voice}</span>
        )}
        {result.escalate && (
          <span className="va-chip va-chip--escalate">🚨 Escalate</span>
        )}
        {result.send_paylink && (
          <span className="va-chip va-chip--paylink">💳 Pay Link</span>
        )}
        <span className="va-chip va-chip--time">
          ⏱ {result.processing_time?.toFixed(2)}s
        </span>
      </div>

      {/* Confidence */}
      {!result.no_speech && (
        <div className="va-conf-section">
          <div className="va-conf-label-row">
            <span>Intent Confidence ({result.intent_method === 'llm_fallback' ? 'LLM fallback' : 'Semantic'})</span>
            <span className="va-conf-pct">{(result.confidence * 100).toFixed(1)}%</span>
          </div>
          <div className="va-conf-bar">
            <div className="va-conf-fill" style={{ width: `${result.confidence * 100}%` }} />
          </div>
        </div>
      )}

      {/* Pipeline Visualizer */}
      <PipelineVisualizer stages={result.pipeline_stages} language={result.language} />

      {/* Response bubbles */}
      {!result.no_speech && (
        <div className="va-chat">
          {result.transcript && (
            <div className="va-bubble va-bubble--user">
              <span className="va-bubble-label">
                {result.native_flag || '🌐'} You said (STT)
                {result.detected_language && result.detected_language !== result.language && (
                  <span className="va-bubble-sublabel"> · detected as {result.detected_language}</span>
                )}
              </span>
              <p className={isKhmer ? 'kh-font' : undefined}>{result.transcript}</p>
            </div>
          )}

          {result.english_translation && (
            <div className="va-bubble va-bubble--translate">
              <span className="va-bubble-label">🌐 English (reasoning language)</span>
              <p>{result.english_translation}</p>
            </div>
          )}

          <div className="va-bubble va-bubble--ai">
            <span className="va-bubble-label">🤖 AI reasoning (English)</span>
            <p>{result.response_en}</p>
          </div>

          <div className="va-bubble va-bubble--ai-kh">
            <span className="va-bubble-label">
              🌏 Translated to Khmer (TTS input)
            </span>
            <p className="kh-font">{result.response_khmer || result.response_native}</p>
          </div>

          {result.language !== 'km-KH' && result.response_native && (
            <div className="va-bubble va-bubble--native">
              <span className="va-bubble-label">
                🔊 TTS transcript ({result.native_language_name})
              </span>
              <p>{result.response_native}</p>
            </div>
          )}
        </div>
      )}

      {result.no_speech && (
        <div className="va-bubble va-bubble--warn">
          <span className="va-bubble-label">⚠️ No speech detected</span>
          <p className={isKhmer ? 'kh-font' : undefined}>{result.response_native}</p>
        </div>
      )}

      {/* Speaker bar */}
      <div className={`va-speaker-bar ${isSpeaking ? 'va-speaker-bar--active' : ''}`}>
        <div className="va-wave-bars">
          {[1,2,3,4,5,6,7,8].map(i => (
            <span key={i} className="va-wave-bar" style={{ animationDelay: `${i * 0.07}s` }} />
          ))}
        </div>
        <span className="va-speaker-label">
          {isSpeaking
            ? `Speaking in ${result.native_language_name} (${result.tts_voice || 'km-KH-PisethNeural'})…`
            : `🔊 ${result.tts_voice || 'km-KH-PisethNeural'} — tap to replay`}
        </span>
        {!isSpeaking && result.tts_audio_base64 && (
          <button
            className="va-replay-btn"
            onClick={() => {
              const audio = new Audio(`data:audio/wav;base64,${result.tts_audio_base64}`);
              audio.play().catch(() => {});
            }}
          >
            ▶ Replay
          </button>
        )}
      </div>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════
//  Main VoiceAssistant component
// ═══════════════════════════════════════════════════════════

export const VoiceAssistant = () => {
  const [isRecording,        setIsRecording]        = useState(false);
  const [language,           setLanguage]           = useState('km-KH');
  const [region,             setRegion]             = useState('Others');
  const [languages,          setLanguages]          = useState(DEFAULT_LANGUAGES);
  const [isProcessing,       setIsProcessing]       = useState(false);
  const [processingStep,     setProcessingStep]     = useState('');
  const [result,             setResult]             = useState(null);
  const [error,              setError]              = useState(null);
  const [testText,           setTestText]           = useState('');
  const [isSpeaking,         setIsSpeaking]         = useState(false);
  const [orbState,           setOrbState]           = useState('idle');
  const [interruptionHandler, setInterruptionHandler] = useState(null);
  const [wasInterrupted,     setWasInterrupted]     = useState(false);

  const filteredLanguages = useMemo(() => {
    if (region === 'India') {
      return Object.fromEntries(
        Object.entries(languages).filter(([code]) => code.endsWith('-IN') || code === 'bn-BD')
      );
    }
    return languages;
  }, [languages, region]);

  useEffect(() => {
    if (Object.keys(filteredLanguages).length > 0 && !filteredLanguages[language]) {
      const first = Object.keys(filteredLanguages)[0];
      setLanguage(first);
    }
  }, [filteredLanguages, language]);

  const mediaRecorderRef = useRef(null);
  const chunksRef        = useRef([]);
  const audioRef         = useRef(null);
  const canvasRef        = useRef(null);
  const orbRef           = useRef(null);
  const animFrameRef     = useRef(null);
  const audioCtxRef      = useRef(null);
  const ttsAudioCtxRef   = useRef(null);
  const ttsAnalyserRef   = useRef(null);

  // ── Canvas frequency visualizer ────────────────────────────────────────

  const startVisualizer = useCallback((analyser, mode) => {
    const canvas = canvasRef.current;
    if (!canvas || !analyser) return;
    const ctx = canvas.getContext('2d');
    const W = canvas.width, H = canvas.height, cx = W / 2, cy = H / 2;
    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);
    const BARS = 72;
    if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);

    const draw = () => {
      animFrameRef.current = requestAnimationFrame(draw);
      analyser.getByteFrequencyData(dataArray);
      ctx.clearRect(0, 0, W, H);
      for (let i = 0; i < BARS; i++) {
        const idx   = Math.floor((i / BARS) * bufferLength * 0.75);
        const value = dataArray[idx] / 255;
        const angle = (i / BARS) * Math.PI * 2 - Math.PI / 2;
        const innerR = 90, barLen = 12 + value * 75, outerR = innerR + barLen;
        const x1 = cx + Math.cos(angle) * innerR, y1 = cy + Math.sin(angle) * innerR;
        const x2 = cx + Math.cos(angle) * outerR, y2 = cy + Math.sin(angle) * outerR;
        const hue = mode === 'mic' ? 185 + value * 75 : 130 + value * 60;
        ctx.strokeStyle = `hsla(${hue},90%,${55 + value * 25}%,${0.5 + value * 0.5})`;
        ctx.lineWidth   = 2.5 + value * 2;
        ctx.lineCap     = 'round';
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
      }
    };
    draw();
  }, []);

  const stopVisualizer = useCallback(() => {
    if (animFrameRef.current) {
      cancelAnimationFrame(animFrameRef.current);
      animFrameRef.current = null;
    }
    const canvas = canvasRef.current;
    if (canvas) canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
  }, []);

  // Orb level CSS variable
  const setOrbLevel = useCallback((level) => {
    if (orbRef.current) orbRef.current.style.setProperty('--level', level);
  }, []);

  // ── Interruption Handler ───────────────────────────────────────────────

  useEffect(() => {
    const handler = initializeInterruptionHandler(
      (interruption) => {
        // Called when user interrupts TTS
        console.log('🛑 User interrupted TTS:', interruption);
        setWasInterrupted(true);

        // Stop TTS playback
        if (audioRef.current) {
          audioRef.current.pause();
        }

        // Notify backend that TTS ended
        if (handler) {
          handler.notifyTTSEnded();
        }

        // Optionally start recording again if user spoke
        if (!isRecording && interruption.hasSpee) {
          console.log('🎤 Restarting recording after interruption');
          setTimeout(() => startRecording(), 100);
        }
      },
      (vadResult) => {
        // Optional: Use VAD result for real-time feedback
        // console.debug('VAD:', vadResult);
      }
    );

    // Connect to WebSocket with error handling
    const wsUrl = `${API_BASE_URL.replace('http', 'ws')}/ws/interruption`;
    handler.connect(wsUrl).catch((err) => {
      console.warn('⚠️  Interruption handler unavailable (WebSocket):', err.message);
      console.info('   Voice interruption detection disabled, but STT/TTS fully functional');
    });

    setInterruptionHandler(handler);

    // Cleanup on unmount
    return () => {
      if (handler) {
        handler.disconnect();
      }
    };
  }, []);

  // ── Recording ──────────────────────────────────────────────────────────

  const startRecording = useCallback(async () => {
    try {
      setError(null);
      setResult(null);
      setWasInterrupted(false);
      chunksRef.current = [];

      // Use enhanced audio constraints for better STT preprocessing
      const stream = await navigator.mediaDevices.getUserMedia(
        getEnhancedAudioConstraints()
      );

      const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      audioCtxRef.current = audioCtx;
      const source   = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.85;
      source.connect(analyser);
      startVisualizer(analyser, 'mic');

      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus' : 'audio/webm';
      const rec = new MediaRecorder(stream, { mimeType });
      mediaRecorderRef.current = rec;

      rec.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      rec.onstop = async () => {
        stream.getTracks().forEach(t => t.stop());
        audioCtxRef.current?.close();
        audioCtxRef.current = null;
        stopVisualizer();
        setOrbLevel(0);
        await sendAudio();
      };

      const levelInterval = createAudioLevelMonitor(analyser, (level) => {
        setOrbLevel(Math.min(level, 1));
      }, 60);
      rec._levelInterval = levelInterval;

      rec.start(200);
      setIsRecording(true);
      setOrbState('listening');
    } catch (err) {
      const friendlyError = getAudioErrorMessage(err);
      setError(friendlyError);
      console.error('Recording error:', err);
    }
  }, [startVisualizer, stopVisualizer, setOrbLevel]);

  const stopRecording = useCallback(() => {
    const rec = mediaRecorderRef.current;
    if (rec && rec.state !== 'inactive') {
      clearInterval(rec._levelInterval);
      rec.stop();
      setIsRecording(false);
      setOrbState('processing');
    }
  }, []);

  // ── Send audio to backend ──────────────────────────────────────────────

  const playTTS = useCallback((audioB64) => {
    if (!audioB64) return;
    const audioEl = audioRef.current;
    const src = `data:audio/wav;base64,${audioB64}`;
    audioEl.src = src;
    const play = () => {
      audioEl.play().catch(e => {
        console.warn('TTS autoplay blocked:', e);
        setOrbState('idle');
      });
    };
    if (audioEl.readyState >= 3) play();
    else audioEl.addEventListener('canplaythrough', play, { once: true });
  }, []);

  const sendAudio = useCallback(async () => {
    setIsProcessing(true);
    setProcessingStep('Running AI pipeline…');
    setOrbState('processing');
    try {
      const blob = new Blob(chunksRef.current, {
        type: mediaRecorderRef.current?.mimeType || 'audio/webm',
      });
      const form = new FormData();
      form.append('file', blob, 'recording.webm');

      const resp = await axios.post(
        `${API_BASE_URL}/voice-input?language=${encodeURIComponent(language)}&region=${encodeURIComponent(region)}`,
        form,
        { headers: { 'Content-Type': 'multipart/form-data' } }
      );
      setResult(resp.data);
      setOrbState('speaking');
      playTTS(resp.data.tts_audio_base64);
    } catch (err) {
      setError(`Pipeline error: ${err.message}`);
      setOrbState('idle');
    } finally {
      setIsProcessing(false);
      setProcessingStep('');
    }
  }, [language, region, playTTS]);

  // ── TTS audio events ───────────────────────────────────────────────────

  useEffect(() => {
    const el = audioRef.current;
    if (!el) return;

    // Setup TTS interruption detection
    if (interruptionHandler) {
      setupTTSWithInterruption(
        el,
        interruptionHandler,
        () => {
          // Called when TTS is interrupted by user
          console.log('🔄 TTS interrupted by user');
          setWasInterrupted(true);
          setIsSpeaking(false);
          setOrbState('idle');
        }
      );
    }

    const onPlay = () => {
      setIsSpeaking(true);
      setOrbState('speaking');

      // Notify backend that TTS started
      if (interruptionHandler) {
        const duration = el.duration * 1000;
        if (duration > 0) {
          interruptionHandler.notifyTTSStarted(Math.round(duration));
        }
      }

      if (!ttsAudioCtxRef.current) {
        try {
          const ctx = new (window.AudioContext || window.webkitAudioContext)();
          const src = ctx.createMediaElementSource(el);
          const analyser = ctx.createAnalyser();
          analyser.fftSize = 256;
          analyser.smoothingTimeConstant = 0.88;
          src.connect(analyser);
          analyser.connect(ctx.destination);
          ttsAudioCtxRef.current = ctx;
          ttsAnalyserRef.current = analyser;
          if (ctx.state === 'suspended') ctx.resume().catch(() => {});
        } catch (e) { console.warn('TTS visualizer setup failed:', e); }
      } else if (ttsAudioCtxRef.current.state === 'suspended') {
        ttsAudioCtxRef.current.resume().catch(() => {});
      }
      if (ttsAnalyserRef.current) startVisualizer(ttsAnalyserRef.current, 'speaker');

      const levelInterval = createAudioLevelMonitor(
        ttsAnalyserRef.current,
        (level) => setOrbLevel(Math.min(level, 1)),
        60
      );
      el._levelInterval = levelInterval;
    };

    const onEnd = () => {
      setIsSpeaking(false);
      setOrbState('idle');
      setOrbLevel(0);
      stopVisualizer();
      clearInterval(el._levelInterval);

      // Notify backend that TTS ended
      if (interruptionHandler) {
        interruptionHandler.notifyTTSEnded();
      }
    };

    el.addEventListener('play',   onPlay);
    el.addEventListener('ended',  onEnd);
    el.addEventListener('pause',  onEnd);
    return () => {
      el.removeEventListener('play',  onPlay);
      el.removeEventListener('ended', onEnd);
      el.removeEventListener('pause', onEnd);
    };
  }, [startVisualizer, stopVisualizer, setOrbLevel, interruptionHandler]);

  // ── Text input ─────────────────────────────────────────────────────────

  const handleTextInput = useCallback(async () => {
    if (!testText.trim()) { setError('Please enter text'); return; }
    try {
      setIsProcessing(true);
      setProcessingStep('Running AI pipeline…');
      setOrbState('processing');
      setError(null);

      const resp = await axios.post(`${API_BASE_URL}/text-input`, {
        text: testText,
        language,
        region,
      });
      setResult(resp.data);
      setOrbState('speaking');
      playTTS(resp.data.tts_audio_base64);
    } catch (err) {
      setError(`Pipeline error: ${err.message}`);
      setOrbState('idle');
    } finally {
      setIsProcessing(false);
      setProcessingStep('');
    }
  }, [testText, language, region, playTTS]);

  // ── Orb label ──────────────────────────────────────────────────────────

  const orbLabel = {
    idle:       'Tap the button to speak',
    listening:  'Listening…',
    processing: processingStep || 'AI pipeline running…',
    speaking:   'Speaking response…',
  }[orbState];

  const orbEmoji = { idle: '🎙', listening: '🎤', processing: '✨', speaking: '🔊' }[orbState];

  // ── Load supported languages from backend so dropdown always matches backend config ─
  useEffect(() => {
    let isMounted = true;
    const loadLanguages = async () => {
      try {
        const resp = await axios.get(`${API_BASE_URL}/languages`);
        const data = resp.data;
        if (!isMounted || !data || typeof data !== 'object') return;
        setLanguages(prev => ({ ...prev, ...data }));
        // Ensure the currently selected language is valid
        if (!data[language]) {
          const first = Object.keys(data)[0];
          if (first) {
            setLanguage(first);
          }
        }
      } catch {
        // Keep DEFAULT_LANGUAGES as graceful fallback
      }
    };
    loadLanguages();
    return () => { isMounted = false; };
  }, []);

  // ─────────────────────────────────────────────────────────────────────
  return (
    <div className="va-root">
      <audio ref={audioRef} style={{ display: 'none' }} />

      <header className="va-header">
        <div className="va-header-badge">SMART VOICE</div>
        <h1>Banking Voice Assistant</h1>
        <p>
          Crystal-clear speech recognition &nbsp;·&nbsp; Real-time interruption &nbsp;·&nbsp;
          Natural, human-like responses
        </p>
      </header>

      <div className="va-body">

        {/* ── LEFT: Controls ────────────────────────────────────────── */}
        <aside className="va-panel va-panel--left">

          {/* Orb */}
          <div className="va-orb-area">
            <div ref={orbRef} className={`va-orb va-orb--${orbState}`} style={{ '--level': 0 }}>
              <div className="va-orb-glow" />
              <canvas ref={canvasRef} className="va-orb-canvas" width="320" height="320" />
              <div className="va-orb-body">
                <span className={`va-orb-emoji ${orbState === 'processing' ? 'va-spin' : ''}`}>
                  {orbEmoji}
                </span>
              </div>
              <div className="va-orb-ring va-ring--1" />
              <div className="va-orb-ring va-ring--2" />
              <div className="va-orb-ring va-ring--3" />
            </div>
            <p className="va-orb-label">{orbLabel}</p>
          </div>

          {/* Controls */}
          <div className="va-controls-card">
            {/* Region */}
            <div className="va-lang-selector">
              <label>Region</label>
              <select
                value={region}
                onChange={e => setRegion(e.target.value)}
                disabled={isRecording || isProcessing}
              >
                <option value="Others">Others (Azure)</option>
                <option value="India">India (Sarvam)</option>
              </select>
            </div>

            {/* Language */}
            <div className="va-lang-selector">
              <label>Language</label>
              <select
                value={language}
                onChange={e => setLanguage(e.target.value)}
                disabled={isRecording || isProcessing}
              >
                {Object.entries(filteredLanguages).map(([code, cfg]) => (
                  <option key={code} value={code}>
                    {cfg.flag} {cfg.name}
                  </option>
                ))}
              </select>
            </div>

            <div className="va-mic-row">
              {!isRecording ? (
                <button
                  className="va-btn va-btn--record"
                  onClick={startRecording}
                  disabled={isProcessing}
                >
                  <span className="va-mic-icon">🎙</span> Start Recording
                </button>
              ) : (
                <button className="va-btn va-btn--stop" onClick={stopRecording}>
                  <span className="va-pulse-dot" /> Stop &amp; Process
                </button>
              )}
            </div>

            {/* Divider */}
            <div className="va-divider">OR TYPE BELOW</div>

            {/* Text */}
            <div className="va-text-section">
              <textarea
                className="va-textarea"
                placeholder={`Type in ${languages[language]?.name || 'your language'}…`}
                value={testText}
                onChange={e => setTestText(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleTextInput(); } }}
                disabled={isProcessing}
                rows={3}
              />
              <button
                className="va-btn va-btn--send"
                onClick={handleTextInput}
                disabled={isProcessing || !testText.trim()}
              >
                Send Message ›
              </button>
            </div>
          </div>

          {error && (
            <div className="va-error-box">
              <span className="va-error-icon">⚠</span>
              {error}
            </div>
          )}

          {wasInterrupted && (
            <div className="va-interrupt-indicator">
              <span className="va-interrupt-icon">🔄</span>
              <span>You interrupted the response</span>
            </div>
          )}
        </aside>

        {/* ── RIGHT: Pipeline + Result ─────────────────────────────── */}
        <main className={`va-panel va-panel--right ${result ? 'va-panel--has-result' : ''}`}>
          {!result && !isProcessing ? (
            <div className="va-empty-state">
              <div className="va-empty-orb"><span>💬</span></div>
              <p className="va-empty-title">Ready to assist</p>
              <p className="va-empty-sub">Speak or type to start the AI pipeline</p>
              <div className="va-pipeline-preview">
                {STAGE_META.map((s, i) => (
                  <React.Fragment key={i}>
                    <span className={`va-pp-badge va-pp-badge--${s.color}`}>{s.icon} {s.label}</span>
                    {i < STAGE_META.length - 1 && <span className="va-pp-arrow">→</span>}
                  </React.Fragment>
                ))}
              </div>
            </div>
          ) : isProcessing ? (
            <div className="va-processing-state">
              <div className="va-processing-spinner" />
              <p className="va-processing-text">{processingStep || 'Running AI pipeline…'}</p>
              <div className="va-processing-stages">
                {STAGE_META.map((s, i) => (
                  <div key={i} className="va-processing-stage">
                    <span>{s.icon}</span>
                    <span>{s.label}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <ResultCard
              result={result}
              isSpeaking={isSpeaking}
              onClose={() => { setResult(null); setOrbState('idle'); }}
            />
          )}
        </main>
      </div>

      <footer className="va-footer">
        <p>
          Secure by design &nbsp;·&nbsp; Built for modern banking experiences &nbsp;·&nbsp;
          © 2026 Banking Voice Assistant
        </p>
      </footer>
    </div>
  );
};

export default VoiceAssistant;
