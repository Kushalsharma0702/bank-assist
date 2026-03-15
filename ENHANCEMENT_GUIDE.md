# Banking Voice Assistant Enhancement Guide

## Overview

This guide explains how to integrate the new interruption logic, advanced STT preprocessing, and humanized TTS into your Banking Voice Assistant.

## Features Added

### 1. **Interruption Logic** ✅
- Real-time Voice Activity Detection (VAD) during TTS playback
- WebSocket communication for instant interruption detection
- Pause/stop TTS when user speaks
- Resume conversation from user input

### 2. **STT Accuracy** ✅
- Spectral noise reduction (Wiener filter + spectral subtraction)
- Voice Activity Detection to remove silence
- Auto-gain control (AGC) for consistent loudness
- Pre/de-emphasis filtering for voice clarity

### 3. **TTS Humanization** ✅
- SSML support for prosody control
- Natural speaking rate and pitch per language
- Emotional expression (where supported)
- Automatic pauses at sentence/clause boundaries
- Multi-language support (Khmer, English, Vietnamese, Thai, etc.)

---

## Backend Installation

### 1. Install Dependencies

```bash
cd backend
pip install librosa scipy numpy  # For audio preprocessing
pip install websockets           # For WebSocket support
```

### 2. Update `requirements.txt`

Add these lines:
```
librosa==0.10.0
scipy==1.11.0
websockets==11.0.3
```

### 3. Environment Variables

Ensure your `.env` file has:
```
AZURE_SPEECH_KEY=your_key_here
AZURE_SPEECH_REGION=southeastasia
AZURE_TRANSLATOR_KEY=your_key_here
AZURE_TRANSLATOR_REGION=southeastasia
```

### 4. File Overview

**New/Modified Backend Files:**

| File | Purpose |
|------|---------|
| `services/audio_preprocessing.py` | **NEW** - Audio enhancement (noise reduction, VAD, AGC) |
| `services/stt_service.py` | **MODIFIED** - STT with preprocessing |
| `services/tts_service.py` | **MODIFIED** - TTS with SSML & humanization |
| `routers/interruption_ws.py` | **NEW** - WebSocket for real-time VAD |
| `main.py` | **MODIFIED** - Registered WebSocket router |

---

## Frontend Integration

### 1. Install Dependencies

```bash
cd frontend
npm install axios  # Already installed
# No additional npm packages needed
```

### 2. Basic Integration (Minimal)

If you only want to enable preprocessing without interruption:

**In `VoiceAssistant.jsx` `startRecording()` function, change audio constraints:**

```javascript
const stream = await navigator.mediaDevices.getUserMedia({
  audio: {
    echoCancellation: true,    // Enable echo cancellation
    noiseSuppression: true,    // Enable noise suppression
    autoGainControl: true,     // Enable AGC
    sampleRate: { ideal: 16000 },
  }
});
```

### 3. Full Integration (With Interruption)

**Step 1: Import utilities at top of `VoiceAssistant.jsx`**

```javascript
import InterruptionHandler from '../utils/InterruptionHandler';
import {
  initializeInterruptionHandler,
  setupTTSWithInterruption,
  getEnhancedAudioConstraints,
} from '../utils/voiceAssistantEnhancements';
```

**Step 2: Add state in component**

```javascript
const [interruptionHandler, setInterruptionHandler] = useState(null);
const [wasInterrupted, setWasInterrupted] = useState(false);
```

**Step 3: Initialize interruption handler on mount**

```javascript
useEffect(() => {
  const handler = initializeInterruptionHandler(
    (interruption) => {
      // Called when user interrupts TTS
      console.log('User interrupted:', interruption);
      setWasInterrupted(true);
      
      // Stop TTS playback
      if (audioRef.current) {
        audioRef.current.pause();
      }
      
      // Optionally start recording again
      if (!isRecording && interruption.hasSpee) {
        startRecording();
      }
    },
    (vadResult) => {
      // Optional: Use VAD result for UI feedback
      console.debug('VAD:', vadResult);
    }
  );

  handler.connect(
    `${API_BASE_URL.replace('http', 'ws')}/ws/interruption`
  ).catch(err => {
    console.warn('Interruption handler unavailable:', err);
  });

  setInterruptionHandler(handler);

  return () => {
    handler.disconnect();
  };
}, []);
```

**Step 4: Setup TTS interruption detection**

```javascript
useEffect(() => {
  const el = audioRef.current;
  if (!el || !interruptionHandler) return;

  // Use the enhanced setup
  setupTTSWithInterruption(
    el,
    interruptionHandler,
    () => {
      // Called when TTS is interrupted
      setWasInterrupted(true);
      setOrbState('idle');
    }
  );

  // Keep existing TTS event handlers if needed
  const onEnded = () => {
    setIsSpeaking(false);
    setOrbState('idle');
    setOrbLevel(0);
    stopVisualizer();
    clearInterval(el._levelInterval);
    
    // Signal backend that TTS ended
    if (interruptionHandler) {
      interruptionHandler.notifyTTSEnded();
    }
  };

  el.addEventListener('ended', onEnded);
  return () => el.removeEventListener('ended', onEnded);
}, [audioRef, interruptionHandler, startVisualizer, stopVisualizer, setOrbLevel]);
```

**Step 5: Update startRecording to use enhanced audio constraints**

```javascript
const startRecording = useCallback(async () => {
  try {
    setError(null);
    setResult(null);
    setWasInterrupted(false);
    chunksRef.current = [];
    
    // Use enhanced audio constraints
    const stream = await navigator.mediaDevices.getUserMedia(
      getEnhancedAudioConstraints()  // ← Use this instead of basic { audio: true }
    );

    // ... rest of recording setup remains the same ...
  } catch (err) {
    setError(`Microphone error: ${err.message}`);
  }
}, []);
```

**Step 6: Show interrupt status in UI**

```javascript
// In JSX, near the orb status display:
{wasInterrupted && (
  <div className="va-interrupt-indicator">
    🔄 You interrupted the response
  </div>
)}
```

---

## Configuration

### STT Preprocessing Options

In `backend/services/stt_service.py`, the `transcribe()` method accepts:

```python
async def transcribe(
    self,
    audio_file_path: str,
    language: str = "km-KH",
    preprocess: bool = True,  # ← Enable/disable preprocessing
) -> Tuple[str, str, float]:
    # ...
```

**Preprocessing includes:**
- ✅ Spectral noise reduction
- ✅ Voice Activity Detection (VAD)
- ✅ Pre/de-emphasis filtering
- ✅ Auto-Gain Control (AGC)

### TTS Humanization Options

In `backend/services/tts_service.py`, the `synthesize()` method accepts:

```python
async def synthesize(
    self,
    text: str,
    language: str = "km-KH",
    output_file: str = "",
    use_ssml: bool = True,        # ← Enable SSML markup
    humanize: bool = True,        # ← Add natural pauses & emotion
) -> Tuple[str, str, str, float]:
    # ...
```

**SSML Features:**
- Natural pauses at sentence/clause boundaries
- Prosody control (rate, pitch)
- Emotional expression (for supported voices)
- Multi-language support

### Voice Configuration

Edit `VOICE_MAP` in `backend/services/tts_service.py` to customize voice characteristics:

```python
"km-KH": {
    "voice": "km-KH-PisethNeural",
    "rate": 0.95,          # 0.5 = slow, 1.0 = normal, 1.25 = fast
    "pitch": 1.0,          # 0.5 = low, 1.0 = normal, 1.5 = high
    "emotion": None,       # Not available for Khmer
},
"en-US": {
    "voice": "en-US-JennyNeural",
    "rate": 0.95,
    "pitch": 1.0,
    "emotion": "friendly",  # Available: friendly, cheerful, empathetic
},
```

---

## Testing

### Test STT Preprocessing

```bash
curl -X POST \
  -F "file=@sample_audio.wav" \
  -F "language=km-KH" \
  http://localhost:8000/voice-input
```

Response should show preprocessing steps:
```json
{
  "pipeline_stages": [
    {
      "name": "STT",
      "output": "ខ្ញុំចង់ដឹងលម្អិតគណនីម",
      "latency_ms": 450
    },
    ...
  ]
}
```

### Test WebSocket Interruption

```javascript
// In browser console:
const ws = new WebSocket('ws://localhost:8000/ws/interruption');
ws.onopen = () => {
  console.log('Connected');
  // Send audio chunks and check for VAD responses
};
```

### Test TTS SSML

Edit `backend/services/tts_service.py` temporarily:

```python
text = "ចូលស្វាគមន៍មកកាន់សេវាឥណទាន។ តើខ្ញុំអាចជួយបានលក្ខណ៍?"
result_file, audio_b64, voice, latency = await tts.synthesize(
    text,
    language="km-KH",
    use_ssml=True,    # Enable SSML
    humanize=True,    # Add natural pauses
)
```

---

## Performance Optimization

### Reduce STT Processing Time

If preprocessing slow, disable VAD:

```python
audio_processed = preprocessor.preprocess_audio(
    audio,
    reduce_noise=True,
    apply_vad=False,      # ← Skip this if too slow
    normalize=True,
)
```

### Optimize TTS

If TTS is slow, disable SSML:

```python
result = await tts.synthesize(
    text,
    language="km-KH",
    use_ssml=False,  # ← Faster, less natural
    humanize=False,
)
```

### WebSocket Latency

Configure client-side chunk size in `InterruptionHandler.js`:

```javascript
this.chunkSize = 16000 * 0.1; // 100ms chunks
// Decrease for faster interruption detection, increase for better efficiency
```

---

## Troubleshooting

### "No such file or directory: librosa"

```bash
pip install librosa
```

### WebSocket connection fails

- Ensure backend is running: `python -m uvicorn backend.main:app --reload`
- Check WebSocket URL: Should be `ws://localhost:8000/ws/interruption`
- Browser must be on HTTPS or localhost for microphone access

### TTS too slow/fast

Adjust `rate` in `VOICE_MAP`:
```python
"rate": 0.95,  # Try 0.85 (slower) or 1.05 (faster)
```

### STT not detecting speech after preprocessing

Increase `VAD threshold`:
```python
preprocessor.vad_threshold = 0.10  # Default is 0.05
```

---

## API Changes

### New Endpoints

#### WebSocket: `/ws/interruption`
Real-time VAD for interruption detection

**Client → Server:**
```json
{
  "type": "audio_chunk",
  "data": "<base64-encoded PCM audio>",
  "sample_rate": 16000
}
```

**Server → Client:**
```json
{
  "type": "vad_result",
  "has_speech": true,
  "confidence": 0.87,
  "should_interrupt": true,
  "action": "interrupt"
}
```

### Modified Endpoints

#### POST `/voice-input`
Now includes preprocessing in STT stage

#### POST `/text-input`
Returns enhanced TTS with SSML processing

---

## Next Steps

1. **Install dependencies** (see Backend Installation)
2. **Test backend** with sample audio
3. **Integrate frontend** (see Frontend Integration)
4. **Test WebSocket** interruption flow
5. **Customize voices** per your requirements
6. **Deploy** to production with proper HTTPS

---

## Support & Notes

- All new code is backward compatible
- Existing API responses unchanged
- Preprocessing can be disabled per request
- SSML generated automatically if enabled
- WebSocket optional (frontend works without it, but interruption unavailable)

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     Frontend (React)                        │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ VoiceAssistant Component                            │   │
│  │  ├─ Microphone Input (Enhanced Constraints)        │   │
│  │  ├─ InterruptionHandler (WebSocket)                │   │
│  │  ├─ TTS Playback with VAD Monitoring               │   │
│  │  └─ UI State Management                            │   │
│  └─────────────────────────────────────────────────────┘   │
│            │                            ↑                    │
│            │ REST                       │ WebSocket           │
│            ↓ (voice/text-input)         │ (ws/interruption)   │
└────────────┼────────────────────────────┼───────────────────┘
             │                            │
┌────────────┼────────────────────────────┼───────────────────┐
│            ↓                            ↓                    │
│                    Backend (FastAPI)                         │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ Voice Router          Interruption WebSocket Router  │   │
│  │  • /voice-input  →    • /ws/interruption            │   │
│  │  • /text-input        • Real-time VAD               │   │
│  └──────────────────────────────────────────────────────┘   │
│            │                                                 │
│  ┌─────────┴──────────────────────────────────────────────┐ │
│  │         Pipeline Orchestrator                          │ │
│  │  ┌──────────────────────────────────────────────────┐  │ │
│  │  │ STT (Azure Speech with Preprocessing)           │  │ │
│  │  │  ├─ Audio Preprocessing                         │  │ │
│  │  │  │  ├─ Spectral Noise Reduction                │  │ │
│  │  │  │  ├─ Voice Activity Detection                │  │ │
│  │  │  │  ├─ Auto-Gain Control                       │  │ │
│  │  │  │  └─ Pre/De-emphasis                         │  │ │
│  │  │  └─ Azure STT Recognition                      │  │ │
│  │  │                                                 │  │ │
│  │  │ Translation → Intent → Workflow → Claude       │  │ │
│  │  │                                                 │  │ │
│  │  │ TTS (Azure Speech with SSML Humanization)      │  │ │
│  │  │  ├─ SSML Generation                            │  │ │
│  │  │  │  ├─ Prosody Control (rate, pitch)           │  │ │
│  │  │  │  ├─ Natural Pauses                          │  │ │
│  │  │  │  ├─ Emotional Expression                    │  │ │
│  │  │  │  └─ Multi-language Support                  │  │ │
│  │  │  └─ Audio Synthesis                            │  │ │
│  │  └──────────────────────────────────────────────────┘  │ │
│  └──────────────────────────────────────────────────────────┘ │
│            │                                                  │
│            ↓                                                  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │      Azure Services                                 │   │
│  │  ├─ Speech-to-Text (STT)                            │   │
│  │  ├─ Text-to-Speech (TTS)                            │   │
│  │  ├─ Translator                                      │   │
│  │  └─ OpenAI / Bedrock (Claude)                      │   │
│  └──────────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────────────┘
```

---

## References

- [Azure Cognitive Services Speech](https://learn.microsoft.com/en-us/azure/cognitive-services/speech-service/)
- [SSML Speech Synthesis Markup Language](https://learn.microsoft.com/en-us/azure/cognitive-services/speech-service/speech-synthesis-markup)
- [Web Audio API](https://developer.mozilla.org/en-US/docs/Web/API/Web_Audio_API)
- [WebSocket API](https://developer.mozilla.org/en-US/docs/Web/API/WebSocket)
