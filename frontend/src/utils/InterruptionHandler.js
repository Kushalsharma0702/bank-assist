/**
 * Interruption Handler
 * 
 * Manages real-time interruption of TTS when user speaks.
 * Features:
 * - Voice Activity Detection (VAD) during TTS playback
 * - Immediate pause/stop of TTS on speech detection
 * - Resume conversation from user's new input
 * - WebSocket communication with backend for VAD analysis
 */

class InterruptionHandler {
  constructor(options = {}) {
    this.ws = null;
    this.isConnected = false;
    this.audioContext = null;
    this.processor = null;
    this.isTTSPlaying = false;
    this.vadThreshold = options.vadThreshold || 0.05;
    this.onInterrupt = options.onInterrupt || (() => {});
    this.onVADResult = options.onVADResult || (() => {});
    this.chunkSize = 16000 * 0.1; // 100ms at 16kHz
  }

  /**
   * Initialize WebSocket connection to backend VAD service
   */
  async connect(wsUrl = 'ws://localhost:8000/ws/interruption') {
    return new Promise((resolve, reject) => {
      try {
        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
          console.log('✅ WebSocket connected for interruption detection');
          this.isConnected = true;
          this.ws.addEventListener('message', this._handleWSMessage.bind(this));
          resolve();
        };

        this.ws.onerror = (error) => {
          console.error('❌ WebSocket connection error:', error);
          this.isConnected = false;
          reject(error);
        };

        this.ws.onclose = () => {
          console.log('WebSocket disconnected');
          this.isConnected = false;
        };
      } catch (error) {
        reject(error);
      }
    });
  }

  /**
   * Start monitoring microphone while TTS is playing
   * Detects if user speaks and sends to backend for VAD analysis
   */
  async startMonitoring(audioContext = null) {
    try {
      if (!this.isConnected) {
        console.warn('WebSocket not connected, skipping VAD monitoring');
        return;
      }

      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true } });
      
      if (!audioContext) {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
      }
      this.audioContext = audioContext;

      // Create audio worklet processor for real-time audio processing
      const source = audioContext.createMediaStreamSource(stream);
      const scriptProcessor = audioContext.createScriptProcessor(4096, 1, 1);

      let buffer = [];

      scriptProcessor.onaudioprocess = (event) => {
        if (!this.isTTSPlaying) {
          return; // Only monitor while TTS is playing
        }

        const inputData = event.inputData.getChannelData(0);
        buffer = buffer.concat(Array.from(inputData));

        // Send chunk when buffer reaches desired size
        if (buffer.length >= this.chunkSize) {
          this._sendAudioChunk(new Float32Array(buffer));
          buffer = [];
        }
      };

      source.connect(scriptProcessor);
      scriptProcessor.connect(audioContext.destination);

      this.stream = stream;
      this.scriptProcessor = scriptProcessor;
      this.source = source;

      console.log('🎤 Microphone monitoring started');
    } catch (error) {
      console.error('Failed to start monitoring:', error);
    }
  }

  /**
   * Stop monitoring microphone
   */
  stopMonitoring() {
    if (this.scriptProcessor) {
      this.scriptProcessor.disconnect();
      this.scriptProcessor = null;
    }
    if (this.source) {
      this.source.disconnect();
      this.source = null;
    }
    if (this.stream) {
      this.stream.getTracks().forEach(track => track.stop());
      this.stream = null;
    }
    console.log('⏹️ Microphone monitoring stopped');
  }

  /**
   * Notify backend that TTS playback started
   */
  notifyTTSStarted(durationMs) {
    if (!this.isConnected) return;
    this.isTTSPlaying = true;
    this.ws.send(JSON.stringify({
      type: 'tts_started',
      duration_ms: durationMs,
    }));
  }

  /**
   * Notify backend that TTS playback ended
   */
  notifyTTSEnded() {
    if (!this.isConnected) return;
    this.isTTSPlaying = false;
    this.ws.send(JSON.stringify({
      type: 'tts_ended',
    }));
    this.stopMonitoring();
  }

  /**
   * Send audio chunk to backend for VAD analysis
   */
  _sendAudioChunk(audioData) {
    try {
      // Convert Float32 to Int16 PCM
      const int16Data = new Int16Array(audioData.length);
      for (let i = 0; i < audioData.length; i++) {
        const sample = Math.max(-1, Math.min(1, audioData[i]));
        int16Data[i] = sample < 0 ? sample * 0x8000 : sample * 0x7FFF;
      }

      // Encode to base64 for WebSocket transmission
      const bytes = new Uint8Array(int16Data.buffer);
      let binaryString = '';
      for (let i = 0; i < bytes.length; i++) {
        binaryString += String.fromCharCode(bytes[i]);
      }
      const base64 = btoa(binaryString);

      // Send VAD request
      if (this.isConnected && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({
          type: 'audio_chunk',
          data: base64,
          sample_rate: 16000,
        }));
      }
    } catch (error) {
      console.error('Failed to send audio chunk:', error);
    }
  }

  /**
   * Handle VAD result from backend
   */
  _handleWSMessage(event) {
    try {
      const result = JSON.parse(event.data);

      if (result.type === 'vad_result') {
        this.onVADResult(result);

        // Trigger interruption if speech detected
        if (result.should_interrupt && result.action === 'interrupt') {
          console.log('🛑 User interrupted — stopping TTS');
          this.onInterrupt({
            hasSpee: result.has_speech,
            confidence: result.confidence,
          });
        }
      } else if (result.type === 'interrupt_command') {
        console.log('📡 Received interrupt command from backend');
        this.onInterrupt({ fromBackend: true });
      }
    } catch (error) {
      console.error('Failed to handle WebSocket message:', error);
    }
  }

  /**
   * Disconnect and cleanup
   */
  disconnect() {
    this.stopMonitoring();
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.isConnected = false;
    console.log('Disconnected from interruption handler');
  }
}

export default InterruptionHandler;
