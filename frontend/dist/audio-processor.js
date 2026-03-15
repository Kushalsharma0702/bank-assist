/**
 * AudioWorklet processor — captures raw PCM from microphone at 16 kHz.
 *
 * The processor runs in a dedicated audio thread, converting Float32 samples
 * to Int16 (which Azure Speech STT expects) and posting binary chunks back
 * to the main thread every ~128 samples (~8 ms at 16 kHz).
 *
 * If the AudioContext is running at a higher sample rate (44100 / 48000),
 * this processor downsamples using linear interpolation so that the backend
 * always receives clean 16 kHz mono PCM.
 */
class PCMProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super(options);
    // inputSampleRate is passed from the main thread
    const opts = (options && options.processorOptions) || {};
    this._nativeSampleRate = opts.nativeSampleRate || sampleRate || 44100;
    this._targetSampleRate = 16000;
    this._ratio = this._nativeSampleRate / this._targetSampleRate;

    // Ring buffer for smooth downsampling
    this._phase = 0;
    this._buf   = [];
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel || channel.length === 0) return true;

    const outSamples = [];

    if (Math.abs(this._ratio - 1) < 0.01) {
      // Already at 16 kHz — no resampling needed
      for (let i = 0; i < channel.length; i++) {
        outSamples.push(channel[i]);
      }
    } else {
      // Linear interpolation downsampling
      for (let i = 0; i < channel.length; i++) {
        this._buf.push(channel[i]);
      }
      while (this._phase < this._buf.length - 1) {
        const idx    = Math.floor(this._phase);
        const frac   = this._phase - idx;
        const sample = this._buf[idx] * (1 - frac) + this._buf[idx + 1] * frac;
        outSamples.push(sample);
        this._phase += this._ratio;
      }
      // Keep only the unprocessed tail
      const keep = Math.floor(this._phase);
      this._buf   = this._buf.slice(keep);
      this._phase -= keep;
    }

    if (outSamples.length === 0) return true;

    // Convert Float32 → Int16 PCM
    const int16 = new Int16Array(outSamples.length);
    for (let i = 0; i < outSamples.length; i++) {
      const clamped = Math.max(-1, Math.min(1, outSamples[i]));
      int16[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7FFF;
    }

    // Transfer (zero-copy) to main thread
    this.port.postMessage(int16.buffer, [int16.buffer]);
    return true;
  }
}

registerProcessor('pcm-processor', PCMProcessor);
