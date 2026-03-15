/**
 * Voice Assistant Enhancements
 * 
 * Utilities to integrate interruption handling and improved audio quality
 * into the VoiceAssistant component
 */

import InterruptionHandler from './InterruptionHandler';

/**
 * Initialize interruption handler with callbacks
 */
export const initializeInterruptionHandler = (onInterrupt, onVADResult) => {
  const handler = new InterruptionHandler({
    onInterrupt,
    onVADResult,
  });

  return handler;
};

/**
 * Setup TTS playback with interruption detection
 * 
 * @param {HTMLAudioElement} audioElement - The audio element playing TTS
 * @param {InterruptionHandler} interruptionHandler - The handler instance
 * @param {Function} onTTSInterrupted - Callback when TTS is interrupted
 */
export const setupTTSWithInterruption = (audioElement, interruptionHandler, onTTSInterrupted) => {
  if (!audioElement || !interruptionHandler) return;

  const onPlay = async () => {
    console.log('▶️ TTS started playing');
    const duration = audioElement.duration * 1000; // Convert to ms
    interruptionHandler.notifyTTSStarted(Math.round(duration));

    // Start monitoring for interruptions
    try {
      await interruptionHandler.startMonitoring();
    } catch (error) {
      console.warn('Failed to start interruption monitoring:', error);
    }
  };

  const onPause = () => {
    if (!audioElement.ended) {
      // User paused, probably due to interruption
      console.log('⏸️ TTS paused (likely interrupted)');
      interruptionHandler.notifyTTSEnded();
      if (onTTSInterrupted) {
        onTTSInterrupted();
      }
    }
  };

  const onEnded = () => {
    console.log('⏹️ TTS finished normally');
    interruptionHandler.notifyTTSEnded();
  };

  audioElement.removeEventListener('play', onPlay);
  audioElement.removeEventListener('pause', onPause);
  audioElement.removeEventListener('ended', onEnded);

  audioElement.addEventListener('play', onPlay);
  audioElement.addEventListener('pause', onPause);
  audioElement.addEventListener('ended', onEnded);
};

/**
 * Enhanced microphone recording with better noise handling
 * Features:
 * - Echo cancellation
 * - Noise suppression
 * - Automatic gain control (AGC)
 * - Voice activity detection
 */
export const getEnhancedAudioConstraints = () => {
  return {
    audio: {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
      sampleRate: { ideal: 16000 },
      channelCount: { ideal: 1 },
    },
  };
};

/**
 * Create audio context with optimal settings
 */
export const createOptimizedAudioContext = () => {
  const AudioContext = window.AudioContext || window.webkitAudioContext;
  const ctx = new AudioContext();

  // Set optimal latency
  if (ctx.latencyHint) {
    ctx.latencyHint('interactive');
  }

  return ctx;
};

/**
 * Monitor audio levels during recording/playback
 */
export const createAudioLevelMonitor = (analyser, callback, interval = 60) => {
  if (!analyser) return null;

  const levelInterval = setInterval(() => {
    const buf = new Uint8Array(analyser.frequencyBinCount);
    analyser.getByteFrequencyData(buf);
    const avg = buf.reduce((s, v) => s + v, 0) / buf.length;
    const level = Math.min(avg / 128, 1);
    callback(level);
  }, interval);

  return levelInterval;
};

/**
 * Message formatter for banking context
 * Adds prosody hints for TTS
 */
export const formatBankingResponse = (text) => {
  // Add emphasis to amounts
  let result = text.replace(
    /\$?(\d+(?:,\d{3})*(?:\.\d{2})?)/g,
    '<prosody pitch="+10%">$$$1</prosody>'
  );

  // Add slight pause after periods
  result = result.replace(/\./g, '.<break time="200ms"/>');

  // Emphasize account/transaction references
  result = result.replace(
    /(account|transaction|card|balance|payment)\s+([A-Z0-9*]+)/gi,
    '<emphasis level="strong">$1 $2</emphasis>'
  );

  return result;
};

/**
 * Validate audio quality before sending to backend
 */
export const validateAudioQuality = (audioData) => {
  if (!audioData || audioData.length === 0) {
    return { valid: false, reason: 'Empty audio' };
  }

  const rms = Math.sqrt(audioData.reduce((sum, s) => sum + s * s, 0) / audioData.length);
  const peak = Math.max(...audioData.map(Math.abs));

  // Check if audio has reasonable energy
  if (rms < 0.01 && peak < 0.1) {
    return { valid: false, reason: 'Too silent', rms, peak };
  }

  // Check for clipping
  if (peak >= 0.95) {
    return { valid: false, reason: 'Clipped/distorted', peak };
  }

  return { valid: true, rms, peak };
};

/**
 * Provide user-friendly error messages
 */
export const getAudioErrorMessage = (error) => {
  const errorMap = {
    'NotAllowedError': 'Microphone permission denied. Please allow microphone access.',
    'NotFoundError': 'No microphone found. Please check your audio devices.',
    'NotReadableError': 'Cannot access microphone. It may be in use by another app.',
    'TypeError': 'Invalid audio configuration.',
    'SecurityError': 'Microphone access blocked by browser security policy.',
  };

  return errorMap[error.name] || `Audio error: ${error.message}`;
};
