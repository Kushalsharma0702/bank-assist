# Banking Voice Assistant - System Architecture Documentation

## 🏗️ High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         WEB BROWSER                              │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │           React Frontend (Vite)                           │   │
│  │  ┌────────────────────────────────────────────────────┐   │   │
│  │  │  VoiceAssistant Component                         │   │   │
│  │  │  - Microphone recording                            │   │   │
│  │  │  - Text input field                               │   │   │
│  │  │  - Results display                                │   │   │
│  │  │  - Audio playback                                 │   │   │
│  │  └────────────────────────────────────────────────────┘   │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTPS/HTTP
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      BACKEND API (FastAPI)                       │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  FastAPI Server (Port 8000)                             │   │
│  │  ┌────────────────────────────────────────────────────┐   │   │
│  │  │  Routes & Controllers                             │   │   │
│  │  │  - POST /voice-input                              │   │   │
│  │  │  - POST /text-input                               │   │   │
│  │  │  - GET /health                                    │   │   │
│  │  │  - GET /audio/{filename}                          │   │   │
│  │  └────────────────────────────────────────────────────┘   │   │
│  └──────────────────────────────────────────────────────────┘   │
│                          │                                        │
│                          ▼                                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Voice Processing Pipeline                              │   │
│  │  ┌────────────────────────────────────────────────────┐   │   │
│  │  │ 1. SpeechRecognitionModule (Azure)                 │   │   │
│  │  │    • Audio file input                              │   │   │
│  │  │    • Language-specific transcription               │   │   │
│  │  │    • Text output                                   │   │   │
│  │  └────────────────────────────────────────────────────┘   │   │
│  │                        │                                    │   │
│  │                        ▼                                    │   │
│  │  ┌────────────────────────────────────────────────────┐   │   │
│  │  │ 2. TranslationEngine (Claude via AWS Bedrock)      │   │   │
│  │  │    • Detect original language                      │   │   │
│  │  │    • Khmer → English translation                   │   │   │
│  │  │    • English → Khmer translation                   │   │   │
│  │  │    • Async processing                              │   │   │
│  │  └────────────────────────────────────────────────────┘   │   │
│  │                        │                                    │   │
│  │                        ▼                                    │   │
│  │  ┌────────────────────────────────────────────────────┐   │   │
│  │  │ 3. IntentEngine (Claude via AWS Bedrock)           │   │   │
│  │  │    • English text classification                   │   │   │
│  │  │    • 12 banking intent types                       │   │   │
│  │  │    • Confidence scoring                            │   │   │
│  │  │    • ThreadPool async execution                    │   │   │
│  │  └────────────────────────────────────────────────────┘   │   │
│  │                        │                                    │   │
│  │                        ▼                                    │   │
│  │  ┌────────────────────────────────────────────────────┐   │   │
│  │  │ 4. ResponseGenerator                               │   │   │
│  │  │    • Intent-based response selection               │   │   │
│  │  │    • Banking terminology                           │   │   │
│  │  │    • Multi-language response pair                  │   │   │
│  │  └────────────────────────────────────────────────────┘   │   │
│  │                        │                                    │   │
│  │                        ▼                                    │   │
│  │  ┌────────────────────────────────────────────────────┐   │   │
│  │  │ 5. TTSModule (Azure Text-to-Speech)                │   │   │
│  │  │    • Khmer response synthesis                      │   │   │
│  │  │    • Neural voice (PisethNeural)                   │   │   │
│  │  │    • WAV file output                               │   │   │
│  │  │    • Temporary file management                     │   │   │
│  │  └────────────────────────────────────────────────────┘   │   │
│  └──────────────────────────────────────────────────────────┘   │
│                          │                                        │
│                          ▼                                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Response Formatting & File Management                  │   │
│  │  - JSON response structure                              │   │
│  │  - Audio file URL generation                            │   │
│  │  - Temporary file cleanup                               │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ JSON + Audio URL
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    EXTERNAL SERVICES                             │
│                                                                   │
│  ┌─────────────────────┐    ┌─────────────────────────────┐    │
│  │ Azure Speech        │    │ AWS Bedrock Claude          │    │
│  │ Services            │    │ (ap-south-1)               │    │
│  │                     │    │                             │    │
│  │ • STT              │    │ • Translation               │    │
│  │ • TTS              │    │ • Intent Detection          │    │
│  │ • Region:          │    │ • Response Generation       │    │
│  │   southeastasia     │    │ • Model:                    │    │
│  │                     │    │   Haiku 3                   │    │
│  └─────────────────────┘    └─────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

## 🔄 Request/Response Flow

### Voice Input Flow (End-to-End)

```
USER SPEAKS INTO MICROPHONE
        │
        ▼
┌──────────────────────────────┐
│ Browser Microphone API       │
│ (getUserMedia)               │
└──────────────────────────────┘
        │
        ├─ Records audio chunks
        ├─ Converts to WAV format
        └─ Builds Blob object
                │
                ▼
        ┌──────────────────────────────┐
        │ POST /voice-input            │
        │ Content-Type: multipart/form │
        │ file: audio_blob             │
        └──────────────────────────────┘
                │
                ▼
        ┌──────────────────────────────────────────────┐
        │ Backend Processing                           │
        │                                               │
        │ 1. Save temp file (/tmp/audio.wav)          │
        │ 2. STT → Transcript                         │
        │ 3. Detect language (Khmer/English)          │
        │ 4. Translate to English (if Khmer)          │
        │ 5. Intent detection                         │
        │ 6. Generate response                        │
        │ 7. Translate response to Khmer              │
        │ 8. TTS synthesis → /tmp/tts_*.wav           │
        │ 9. Cleanup temp files                       │
        └──────────────────────────────────────────────┘
                │
                ▼
        ┌──────────────────────────────┐
        │ JSON Response:               │
        │ {                            │
        │   language: "km-KH",         │
        │   transcript: "...",         │
        │   intent: "FULL_PAYMENT",    │
        │   response_kh: "...",        │
        │   tts_audio_url: "/audio/...",
        │   processing_time: 2.34      │
        │ }                            │
        └──────────────────────────────┘
                │
                ▼
        ┌──────────────────────────────┐
        │ Frontend Display             │
        │ • Show transcript            │
        │ • Display detected intent    │
        │ • Play audio response        │
        │ • Update UI state            │
        └──────────────────────────────┘
                │
                ▼
        AUDIO PLAYS THROUGH SPEAKERS
```

## 📊 Data Models

### Request Models

```
VoiceInputRequest:
├── file: UploadFile
└── language: str (km-KH|en-US)

TextInputRequest:
├── text: str
└── language: str (km-KH|en-US)
```

### Response Model

```
VoiceResponse:
├── language: str (km-KH|en-US)
├── transcript: str
├── english_translation: str
├── intent: str (12 options)
├── confidence: float (0.0-1.0)
├── response_en: str
├── response_kh: str
├── tts_audio_url: str
└── processing_time: float
```

## 🧵 Threading & Async Model

```
Main Event Loop (asyncio)
│
├─ Request Handler (async)
│  │
│  ├─ File handling
│  │
│  ├─ [ThreadPool Executor]
│  │  ├─ STT (Azure SDK - blocking I/O)
│  │  ├─ Translation (Claude API call)
│  │  ├─ Intent detection (Claude API call)
│  │  └─ TTS (Azure SDK - blocking I/O)
│  │
│  └─ Response formatting
│
└─ Other concurrent requests
```

## 🔐 Security Architecture

```
┌─────────────────────────────────┐
│ CORS Middleware                  │
│ Allow origins: *                │
│ Allow methods: *                │
│ Allow headers: *                │
└─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│ API Endpoints                    │
│ Input validation (Pydantic)     │
│ File size limits                │
└─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│ Azure & AWS Credentials          │
│ Stored in .env (not in code)    │
│ Not logged or exposed           │
└─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│ Temporary File Management        │
│ Auto-delete after use           │
│ /tmp isolation                  │
└─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│ Error Handling                   │
│ No stack traces exposed         │
│ Safe error messages             │
└─────────────────────────────────┘
```

## 📈 Performance Characteristics

```
Component               | Typical Latency
─────────────────────────────────────────
STT (Azure)            | 1-3 seconds
Translation (Claude)   | 1-2 seconds
Intent Detection       | 1-2 seconds
Response Generation    | < 1 second
TTS (Azure)            | 2-4 seconds
Network Round-trip     | 0.2-0.5 seconds
─────────────────────────────────────────
Total Pipeline         | 6-13 seconds
```

## 🗂️ File Structure

```
vsco/
├── backend/
│   ├── main.py              (700+ lines, fully featured)
│   ├── requirements.txt      (Dependencies)
│   └── package.json
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── VoiceAssistant.jsx    (450+ lines React)
│   │   │   └── VoiceAssistant.css    (500+ lines styling)
│   │   ├── main.jsx
│   │   └── index.css
│   ├── index.html
│   ├── package.json
│   └── vite.config.js
│
├── docker-compose.yml
├── Dockerfile.backend
├── Dockerfile.frontend
├── nginx.conf
├── .env.example
├── README.md
├── SETUP.md
└── ARCHITECTURE.md (this file)
```

## 🎯 Deployment Scenarios

### Scenario 1: Local Development
```
Developer Machine
├─ Python venv
├─ Node.js npm
├─ Backend: localhost:8000
└─ Frontend: localhost:5173
```

### Scenario 2: Docker Local
```
Docker Engine
├─ Backend Container (8000)
├─ Frontend Container (80)
└─ Shared network
```

### Scenario 3: Cloud Deployment (AWS)
```
AWS EC2
├─ Docker Compose running
├─ ECS for container management
├─ RDS for database (future)
├─ S3 for audio storage (future)
├─ CloudFront CDN
└─ Route53 DNS
```

### Scenario 4: Kubernetes
```
K8s Cluster
├─ Backend Deployment (3+ replicas)
├─ Frontend Deployment (3+ replicas)
├─ Service Load Balancer
├─ ConfigMap for env vars
├─ Secrets for credentials
└─ Persistent Volume for temp files
```

## 🔄 Data Flow Diagrams

### Complete Voice Processing Pipeline

```
┌─────────────┐
│ Audio Input │
└──────┬──────┘
       │
       ▼
┌─────────────────────────────┐
│ Azure STT                    │
│ Input: audio_file            │
│ Output: transcript text      │
└──────┬──────────────────────┘
       │
       ▼
┌─────────────────────────────┐
│ Language Detection           │
│ (Khmer vs English)          │
└──────┬──────────────────────┘
       │
       ├─── If Khmer ───┐
       │                │
       │                ▼
       │        ┌──────────────────┐
       │        │ Claude Translate │
       │        │ (Khmer→English)  │
       │        └────┬─────────────┘
       │             │
       │        ┌────▼─────────────┐
       └──────→ │ English Text     │
                └────┬─────────────┘
                     │
                     ▼
        ┌────────────────────────────┐
        │ Claude Intent Detection    │
        │ Input: English text        │
        │ Output: intent + score     │
        └────┬─────────────────────┘
             │
             ▼
        ┌────────────────────────────┐
        │ Response Generator         │
        │ Input: intent              │
        │ Output: response pair      │
        └────┬─────────────────────┘
             │
             ├─→ Response EN
             │
             └─→ Response KH
                    │
                    ▼
        ┌────────────────────────────┐
        │ Azure TTS                  │
        │ Input: Khmer response      │
        │ Output: audio WAV          │
        └────┬─────────────────────┘
             │
             ▼
        ┌────────────────────────────┐
        │ Audio Response             │
        │ (Played by frontend)       │
        └────────────────────────────┘
```

## 🚀 Scalability Strategy

```
Single Server
└── Monolithic FastAPI

     │
     ├─ Hits bottleneck ~100 concurrent users
     │
     ▼

Load Balanced
├── FastAPI Backend (3 instances)
├── Nginx Load Balancer
├── Shared temp storage
└── Supports ~500 concurrent users

     │
     └─ Hits database bottleneck (if added)
     │
     ▼

Microservices
├── API Gateway
├── STT Service
├── Translation Service
├── Intent Service
├── TTS Service
├── Caching Layer (Redis)
├── Message Queue (RabbitMQ)
└── Supports ~10k+ concurrent users
```

## 📞 Support & Maintenance

### Monitoring Points

1. **Backend Health**
   - /health endpoint response time
   - Error rate
   - Average processing latency

2. **External Services**
   - Azure Speech quota usage
   - AWS Bedrock API calls
   - Error rates from services

3. **Frontend**
   - Page load time
   - JavaScript errors
   - Microphone API failures

### Maintenance Tasks

- Weekly: Review logs for errors
- Monthly: Update dependencies
- Quarterly: Security audit
- Annually: Performance review

---

**Document Version:** 1.0  
**Last Updated:** March 6, 2026  
**Status:** Complete ✅
