# Banking Voice Assistant - System Diagrams

## 1. High-Level System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    USER INTERFACE (React)                    │
│  ┌───────────────────────────────────────────────────────┐   │
│  │  • Microphone input                                    │   │
│  │  • Language selection                                  │   │
│  │  • Text testing field                                  │   │
│  │  • Results display                                     │   │
│  │  • Audio playback                                      │   │
│  └───────────────────────────────────────────────────────┘   │
└──────────────────────────────┬──────────────────────────────┘
                               │ HTTP/REST API
                               ▼
┌─────────────────────────────────────────────────────────────┐
│              BACKEND API SERVER (FastAPI)                    │
│  ┌───────────────────────────────────────────────────────┐   │
│  │  Voice Processing Pipeline                            │   │
│  │  ┌─────────────────────────────────────────────────┐  │   │
│  │  │ 1. STT (Azure Speech SDK)                       │  │   │
│  │  │ 2. Translation (Claude)                         │  │   │
│  │  │ 3. Intent Detection (Claude)                    │  │   │
│  │  │ 4. Response Generation                          │  │   │
│  │  │ 5. TTS (Azure Speech SDK)                       │  │   │
│  │  └─────────────────────────────────────────────────┘  │   │
│  └───────────────────────────────────────────────────────┘   │
└──────────────────┬──────────────────┬──────────────────────┘
                   │                  │
          ┌────────▼──────┐  ┌────────▼──────┐
          │ Azure Speech  │  │ AWS Bedrock   │
          │ STT/TTS       │  │ Claude        │
          └───────────────┘  └───────────────┘
```

## 2. Request/Response Cycle

```
Browser                              Backend                  External APIs
  │                                    │                          │
  ├─ User speaks or types ─────┐       │                          │
  │                             │       │                          │
  │                             ▼       │                          │
  │                        POST /voice-input                       │
  │                        or /text-input ────┐                    │
  │                             │              │                   │
  │                             │              ▼                   │
  │                             │         STT (if voice)           │
  │                             │         Transcript ──────────────┤──► Azure Speech
  │                             │              │                   │
  │                             │              ▼                   │
  │                             │         Detect Language          │
  │                             │         Translate if needed ────────┤──► Claude
  │                             │              │                   │
  │                             │              ▼                   │
  │                             │         Intent Detection ────────┤──► Claude
  │                             │              │                   │
  │                             │              ▼                   │
  │                             │         Generate Response        │
  │                             │              │                   │
  │                             │              ▼                   │
  │                             │         TTS Synthesis ──────────┤──► Azure Speech
  │                             │              │                   │
  │                    ◄────────┴──────────────┤                   │
  │ ← JSON Response                            │                   │
  │    (transcript, intent, response, audio_url)                   │
  │                                            │                   │
  ▼                                            │                   │
Display results & play audio                   │                   │
```

## 3. Voice Processing Pipeline

```
┌──────────────────────────────────────────────────────────┐
│                   VOICE PROCESSING                         │
└──────────────────────────────────────────────────────────┘
           │
           ▼
    ┌─────────────┐
    │   INPUT     │
    │ Audio File  │
    │ OR Text     │
    └──────┬──────┘
           │
           ▼
    ┌──────────────────────┐
    │ STT (Speech to Text) │   ◄─── Azure Speech SDK
    │ (if audio input)     │
    │ Output: Transcript   │
    └──────┬───────────────┘
           │
           ▼
    ┌──────────────────────┐
    │ Language Detection   │
    │ Khmer or English?    │
    └──────┬───────────────┘
           │
      ┌────┴────┐
      │          │
      ▼          ▼
   Khmer    English
      │          │
      ▼          │
  Translate      │
  to English     │
      │          │
      └────┬─────┘
           │
           ▼
    ┌──────────────────────┐
    │ Intent Detection     │   ◄─── Claude via AWS Bedrock
    │ (12 intent types)    │
    │ Output: intent +     │
    │         confidence   │
    └──────┬───────────────┘
           │
           ▼
    ┌──────────────────────┐
    │ Response Generation  │
    │ (Banking responses)  │
    │ Output: EN + KH      │
    └──────┬───────────────┘
           │
           ▼
    ┌──────────────────────┐
    │ TTS (Text to Speech) │   ◄─── Azure Speech SDK
    │ Khmer voice synth    │
    │ Output: Audio WAV    │
    └──────┬───────────────┘
           │
           ▼
    ┌──────────────────────┐
    │      OUTPUT          │
    │ • Transcript         │
    │ • Translation        │
    │ • Intent             │
    │ • Response (EN/KH)   │
    │ • Audio URL          │
    └──────────────────────┘
```

## 4. Intent Classification Hierarchy

```
Customer Input
      │
      ▼
┌──────────────────────────────┐
│  12 Banking Intent Types     │
├──────────────────────────────┤
│ ┌──────────────┐             │
│ │  GREETING    │             │
│ └──────────────┘             │
│                              │
│ ┌──────────────┐             │
│ │ ACCOUNT_     │             │
│ │ INQUIRY      │             │
│ └──────────────┘             │
│                              │
│ ┌──────────────┐             │
│ │ TRANSACTION_ │             │
│ │ INQUIRY      │             │
│ └──────────────┘             │
│                              │
│ ┌──────────────┐             │
│ │ FULL_        │             │
│ │ PAYMENT      │             │
│ └──────────────┘             │
│                              │
│ ┌──────────────┐             │
│ │ PARTIAL_     │             │
│ │ PAYMENT      │             │
│ └──────────────┘             │
│                              │
│ ┌──────────────┐             │
│ │ PAYMENT_     │             │
│ │ DIFFICULTY   │             │
│ └──────────────┘             │
│                              │
│ ┌──────────────┐             │
│ │ PROMISE_TO_  │             │
│ │ PAY          │             │
│ └──────────────┘             │
│                              │
│ ┌──────────────┐             │
│ │  DISPUTE     │             │
│ └──────────────┘             │
│                              │
│ ┌──────────────┐             │
│ │ CALL_BACK    │             │
│ └──────────────┘             │
│                              │
│ ┌──────────────┐             │
│ │ HUMAN_       │             │
│ │ AGENT        │             │
│ └──────────────┘             │
│                              │
│ ┌──────────────┐             │
│ │ NOT_         │             │
│ │ INTERESTED   │             │
│ └──────────────┘             │
│                              │
│ ┌──────────────┐             │
│ │  UNKNOWN     │             │
│ └──────────────┘             │
└──────────────────────────────┘
```

## 5. Frontend Component Hierarchy

```
App
├── Header
│   ├── Title
│   └── Subtitle
│
├── MainContent
│   ├── ControlPanel
│   │   ├── LanguageSelector
│   │   ├── RecordingSection
│   │   │   ├── StartButton
│   │   │   └── StopButton
│   │   ├── TextInputSection
│   │   │   ├── TextArea
│   │   │   └── SendButton
│   │   └── ProcessingIndicator
│   │       ├── Spinner
│   │       └── StatusMessage
│   │
│   └── ResultsPanel (conditional)
│       ├── InfoGrid
│       │   ├── LanguageDetected
│       │   ├── IntentDetected
│       │   ├── Confidence
│       │   └── ProcessingTime
│       ├── TranscriptBox
│       ├── TranslationBox
│       ├── ResponsesGrid
│       │   ├── ResponseEN
│       │   └── ResponseKH
│       ├── AudioSection
│       │   └── AudioPlayer
│       └── ClearButton
│
└── Footer
    ├── APIUrl
    └── Copyright
```

## 6. Data Flow - Text Input Example

```
User types: "ខ្ញុំចង់សងប្រាក់"
         │
         ▼
POST /text-input
{
  "text": "ខ្ញុំចង់សងប្រាក់",
  "language": "km-KH"
}
         │
         ▼
Backend Processing:
  1. Text Input: "ខ្ញុំចង់សងប្រាក់"
  2. Translation: "I want to pay"
  3. Intent Detection:
     - Intent: FULL_PAYMENT
     - Confidence: 0.95
  4. Response EN: "I can help you make a payment."
  5. Response KH: "ខ្ញុំអាចជួយអ្នកបង់ប្រាក់បាន។"
  6. TTS: /tmp/tts_1234567890.wav
         │
         ▼
Response JSON:
{
  "language": "km-KH",
  "transcript": "ខ្ញុំចង់សងប្រាក់",
  "english_translation": "I want to pay",
  "intent": "FULL_PAYMENT",
  "confidence": 0.95,
  "response_en": "I can help you make a payment.",
  "response_kh": "ខ្ញុំអាចជួយអ្នកបង់ប្រាក់បាន។",
  "tts_audio_url": "/audio/tts_1234567890.wav",
  "processing_time": 2.34
}
         │
         ▼
Frontend Display:
├─ Language: km-KH (Khmer)
├─ Intent: FULL_PAYMENT
├─ Confidence: 95%
├─ Transcript: ខ្ញុំចង់សងប្រាក់
├─ Translation: I want to pay
├─ Response EN: I can help you make a payment.
├─ Response KH: ខ្ញុំអាចជួយអ្នកបង់ប្រាក់បាន។
└─ Audio: [Play button] ► Play TTS Audio
```

## 7. Deployment Architecture (Docker)

```
┌────────────────────────────────────┐
│      Docker Compose Network        │
├────────────────────────────────────┤
│                                     │
│  ┌──────────────────────────────┐  │
│  │   Frontend Container         │  │
│  │   (Node.js + Vite)          │  │
│  │   Port: 80/5173             │  │
│  │   ┌────────────────────────┐ │  │
│  │   │ Nginx Web Server       │ │  │
│  │   │ Serve React App        │ │  │
│  │   │ Static files           │ │  │
│  │   └────────────────────────┘ │  │
│  └──────────────┬───────────────┘  │
│                 │                   │
│                 │ HTTP              │
│                 ▼                   │
│  ┌──────────────────────────────┐  │
│  │   Backend Container          │  │
│  │   (Python FastAPI)           │  │
│  │   Port: 8000                 │  │
│  │   ┌────────────────────────┐ │  │
│  │   │ Uvicorn Server         │ │  │
│  │   │ Voice Pipeline         │ │  │
│  │   │ API Endpoints          │ │  │
│  │   └────────────────────────┘ │  │
│  └──────────────────────────────┘  │
│                 │                   │
│  ┌──────────────┴───────────────┐  │
│  │   Shared Volume (/tmp)       │  │
│  │   Temporary audio files      │  │
│  └──────────────────────────────┘  │
│                                     │
└────────────────────────────────────┘
         │                    │
         │                    │
    ┌────▼─────┐         ┌────▼──────┐
    │ Internet  │         │ Localhost │
    │ (Public)  │         │ (Dev)     │
    └───────────┘         └───────────┘
```

## 8. Async Processing Model

```
Main Event Loop
│
├─ Request 1: Voice input
│  ├─ File handling (fast)
│  ├─ [ThreadPool] STT (1-3s)
│  ├─ [ThreadPool] Translation (1-2s)
│  ├─ [ThreadPool] Intent (1-2s)
│  ├─ Response generation (< 1s)
│  ├─ [ThreadPool] TTS (2-4s)
│  └─ Response formatting (fast)
│
├─ Request 2: Health check (concurrent)
│  └─ Response (immediate)
│
└─ Request 3: Audio download (concurrent)
   └─ File serving (fast)
```

## 9. Error Handling Flow

```
Request Input
     │
     ▼
┌─────────────────────┐
│ Input Validation    │
│ (Pydantic)          │
└────┬────────────────┘
     │
  Valid? ─No─► Error 400 (Bad Request)
     │
    Yes
     │
     ▼
┌─────────────────────┐
│ STT Processing      │
└────┬────────────────┘
     │
  Success? ─No─► Error 500 (Transcription failed)
     │
    Yes
     │
     ▼
┌─────────────────────┐
│ Translation         │
└────┬────────────────┘
     │
  Success? ─No─► Error 500 (Translation failed)
     │
    Yes
     │
     ▼
┌─────────────────────┐
│ Intent Detection    │
└────┬────────────────┘
     │
  Success? ─No─► Fallback (UNKNOWN intent)
     │
    Yes
     │
     ▼
┌─────────────────────┐
│ TTS Synthesis       │
└────┬────────────────┘
     │
  Success? ─No─► Error 500 (TTS failed)
     │
    Yes
     │
     ▼
Success Response 200 ✓
```

---

**All diagrams represent the actual system architecture.** Use these diagrams to understand:
- How requests flow through the system
- Component relationships
- Data transformations
- Error handling paths
- Deployment structure

---

**Version**: 1.0  
**Status**: Complete ✅
