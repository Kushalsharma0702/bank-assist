# Banking Voice Assistant - Setup & Deployment Guide

## 📦 Complete System Overview

This is a **production-grade, full-stack multilingual banking voice assistant** with:

- **Backend**: Python FastAPI with async voice processing pipeline
- **Frontend**: React with Vite for real-time UI
- **Services**: Azure Speech SDK, AWS Bedrock Claude, Translation
- **Languages**: Khmer (km-KH) and English (en-US)

## 🎯 Key Features

✅ Real-time voice input via microphone  
✅ Speech-to-text with language detection  
✅ Translation (Khmer ↔ English)  
✅ Intent classification (12 banking intents)  
✅ AI-powered response generation  
✅ Text-to-speech output  
✅ Web UI with real-time display  
✅ Beta testing mode (text input)  
✅ Docker containerization  
✅ Production-ready logging  

## 📋 Prerequisites

### System Requirements
- Python 3.10 or higher
- Node.js 18 or higher
- Docker & Docker Compose (optional)
- 2GB RAM minimum
- Internet connection

### API Credentials Required
1. **Azure Speech Services**
   - Subscription key
   - Region (e.g., southeastasia)

2. **AWS Bedrock**
   - Access key ID
   - Secret access key
   - Region (ap-south-1)
   - Claude 3 Haiku model access

## 🚀 Installation & Setup

### Step 1: Clone/Prepare Project

```bash
# Navigate to vsco directory
cd /path/to/vsco
```

### Step 2: Configure Environment

```bash
# Copy example to .env
cp .env.example .env

# Edit .env with your credentials
nano .env
# or
vim .env
```

**Required credentials:**
```env
AZURE_SPEECH_KEY=xxxxxxxxxxxxxxxx
AZURE_SPEECH_REGION=southeastasia
AWS_ACCESS_KEY_ID=xxxxxxxxxxxxxxxx
AWS_SECRET_ACCESS_KEY=xxxxxxxxxxxxxxxx
AWS_REGION=ap-south-1
CLAUDE_MODEL_ID=anthropic.claude-3-haiku-20240307-v1:0
```

---

## 🏃 Option A: Local Development Setup

### Backend Setup

```bash
# Navigate to backend directory
cd backend

# Create Python virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run server
python main.py
```

**Expected Output:**
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete
```

### Frontend Setup (New Terminal)

```bash
# Navigate to frontend directory
cd frontend

# Install dependencies
npm install

# Run development server
npm run dev
```

**Expected Output:**
```
  VITE v5.0.8  ready in 234 ms

  ➜  Local:   http://localhost:5173/
  ➜  Network: use --host to expose
```

### Access Application

Open browser: **http://localhost:5173**

---

## 🐳 Option B: Docker Deployment

### Build & Run

```bash
# From vsco directory
docker-compose up --build
```

**Expected Output:**
```
banking-voice-backend   | INFO:     Uvicorn running on http://0.0.0.0:8000
banking-voice-frontend  | Listening on http://0.0.0.0:80
```

### Access Application

- Frontend: **http://localhost:5173**
- Backend: **http://localhost:8000**
- API Docs: **http://localhost:8000/docs**

### Stop Services

```bash
docker-compose down
```

---

## 🧪 Testing the System

### Method 1: Text Input (Recommended for Testing)

1. Open frontend: http://localhost:5173
2. Click language selector (Khmer/English)
3. Enter text in "Text Input (Beta Testing)" section
4. Click "Send Text"
5. View results and listen to audio response

### Method 2: Voice Input (Requires Microphone)

1. Open frontend: http://localhost:5173
2. Allow microphone permission when prompted
3. Click "Start Recording"
4. Speak into microphone
5. Click "Stop Recording"
6. View results and listen to audio response

### Test Scenarios

#### Khmer Test
```
Input: "ខ្ញុំចង់សងប្រាក់ពេញលេញ"
Expected Intent: FULL_PAYMENT
Response: Khmer banking response
```

#### English Test
```
Input: "Can you help me check my account balance?"
Expected Intent: ACCOUNT_INQUIRY
Response: English banking response (in Khmer voice)
```

#### Greeting Test
```
Input: "Hello" or "សាលូបឆ្នាំថ្មី"
Expected Intent: GREETING
Response: Welcome message
```

---

## 📊 API Testing with cURL

### Health Check

```bash
curl http://localhost:8000/health
```

Response:
```json
{
  "status": "healthy",
  "timestamp": "2024-01-01T12:00:00.123456",
  "service": "Banking Voice Assistant API"
}
```

### Text Input Test

```bash
curl -X POST http://localhost:8000/text-input \
  -H "Content-Type: application/json" \
  -d '{
    "text": "I want to make a payment",
    "language": "en-US"
  }'
```

### Voice Input Test (with audio file)

```bash
curl -X POST "http://localhost:8000/voice-input?language=en-US" \
  -F "file=@recording.wav"
```

---

## 📈 Monitoring & Logs

### Backend Logs

```bash
# View real-time logs
docker-compose logs -f backend

# View specific service
docker-compose logs backend

# View last 100 lines
docker-compose logs --tail=100 backend
```

### Frontend Logs

Browser console (F12):
- Open DevTools
- Go to Console tab
- View client-side logs

---

## 🔧 Troubleshooting

### Problem: "Connection refused" on port 8000

**Solution:**
```bash
# Check if port is in use
lsof -i :8000

# Use different port
python main.py  # Change port in main.py or use environment variable
```

### Problem: Azure Speech SDK error

**Error Message:** `AuthorizationError`

**Solution:**
```bash
# Verify credentials in .env
cat .env | grep AZURE

# Test API key
curl "https://{REGION}.tts.speech.microsoft.com/cognitiveservices/v1" \
  -H "Ocp-Apim-Subscription-Key: {YOUR_KEY}"
```

### Problem: AWS Bedrock "Invalid credentials"

**Solution:**
```bash
# Verify AWS credentials
aws sts get-caller-identity

# If error, reconfigure
aws configure
```

### Problem: Microphone not working

**Solution:**
```
1. Check browser microphone permissions
2. Ensure HTTPS (if deployed)
3. Allow microphone in browser settings
4. Test with text input first
```

### Problem: Docker containers won't start

**Solution:**
```bash
# Check Docker status
docker ps -a

# View error logs
docker-compose logs backend

# Rebuild containers
docker-compose down
docker-compose up --build
```

---

## 🔐 Security Checklist

Before production deployment:

- [ ] Environment variables not in git
- [ ] .env file is in .gitignore
- [ ] Change default credentials
- [ ] Enable HTTPS
- [ ] Set up API rate limiting
- [ ] Configure CORS for your domain
- [ ] Enable authentication/authorization
- [ ] Set up monitoring & alerting
- [ ] Regular security audits
- [ ] Backup strategy in place

---

## 📊 Performance Tuning

### Backend Optimization

```python
# Increase worker threads for Bedrock calls
# In main.py, line ~35:
executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
```

### Frontend Optimization

```bash
# Build optimized production bundle
npm run build

# This creates dist/ with minified assets
```

### Docker Resource Limits

```yaml
# In docker-compose.yml
services:
  backend:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
```

---

## 📚 API Endpoints Reference

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | /health | Health check |
| POST | /voice-input | Process audio file |
| POST | /text-input | Process text input |
| GET | /audio/{filename} | Download audio file |

---

## 🚢 Production Deployment

### Using Gunicorn (Python)

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:8000 main:app
```

### Using Nginx Reverse Proxy

```nginx
upstream backend {
    server localhost:8000;
}

server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://backend;
        proxy_set_header Host $host;
    }
}
```

### Using AWS EC2

1. Launch EC2 instance (Ubuntu 22.04)
2. Install Docker: `curl -fsSL https://get.docker.com | sh`
3. Clone repository
4. Configure .env
5. Run: `docker-compose up -d`

### Using Heroku

```bash
# Create app
heroku create your-app-name

# Set environment variables
heroku config:set AZURE_SPEECH_KEY=xxx

# Deploy
git push heroku main
```

---

## 📞 Support & Debugging

### Enable Verbose Logging

```python
# In main.py, line 20:
logging.basicConfig(
    level=logging.DEBUG,  # Change from INFO to DEBUG
    format='%(asctime)s | %(levelname)-8s | %(message)s'
)
```

### Common Issues & Solutions

| Issue | Cause | Solution |
|-------|-------|----------|
| 503 Service Unavailable | Backend down | Check `docker-compose logs backend` |
| CORS error | Frontend origin not allowed | Update CORS in main.py |
| 401 Unauthorized | Invalid credentials | Verify .env settings |
| Audio not playing | Missing TTS output | Check /tmp directory |
| Slow response | High latency | Check network, increase timeouts |

---

## 📈 Scalability

For production use with high traffic:

1. **Horizontal Scaling**
   - Run multiple backend instances
   - Use load balancer (NGINX, HAProxy)

2. **Vertical Scaling**
   - Increase machine resources (CPU, RAM)
   - Use larger instance types

3. **Caching**
   - Cache frequent translations
   - Cache intent detection results
   - Use Redis for session management

4. **Async Processing**
   - Queue voice processing jobs
   - Use background workers
   - Process in batches

---

## 🎓 Learning Resources

- FastAPI: https://fastapi.tiangolo.com/
- React: https://react.dev/
- Azure Speech: https://learn.microsoft.com/en-us/azure/ai-services/speech-service/
- AWS Bedrock: https://docs.aws.amazon.com/bedrock/

---

## ✅ Checklist for Go-Live

- [ ] All credentials configured
- [ ] Security review completed
- [ ] Performance tested
- [ ] Error handling verified
- [ ] Logging implemented
- [ ] Monitoring setup
- [ ] Backup tested
- [ ] Documentation complete
- [ ] Team trained
- [ ] Go-live approval

---

**Version:** 1.0.0  
**Last Updated:** March 6, 2026  
**Status:** Production Ready ✅
