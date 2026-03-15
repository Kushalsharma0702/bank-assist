#!/bin/bash

# Banking Voice Assistant - Enhancement Setup Script
# This script installs all dependencies for the new features:
# - Interruption logic
# - Advanced STT preprocessing
# - Humanized TTS

set -e

echo "🚀 Banking Voice Assistant Enhancement Setup"
echo "=============================================="
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check Python version
echo -e "${BLUE}📋 Checking Python version...${NC}"
python_version=$(python3 --version 2>&1)
echo "✅ Found: $python_version"
echo ""

# Install backend dependencies
echo -e "${BLUE}📦 Installing backend dependencies...${NC}"
cd backend || exit 1

# Create/update requirements.txt with new packages
echo "Adding new audio processing libraries..."
pip install librosa==0.10.0 -q
pip install scipy==1.11.0 -q
pip install websockets==11.0.3 -q

echo "Installing all backend requirements..."
pip install -r requirements.txt -q

echo "✅ Backend dependencies installed"
echo ""

# Check if frontend exists and install
if [ -d "../frontend" ]; then
    echo -e "${BLUE}📦 Checking frontend dependencies...${NC}"
    cd ../frontend || exit 1
    
    if command -v npm &> /dev/null; then
        echo "✅ npm found, ensuring axios is installed..."
        npm ls axios > /dev/null 2>&1 || npm install axios -q
        echo "✅ Frontend dependencies ready"
    else
        echo -e "${YELLOW}⚠️  npm not found. Frontend setup skipped.${NC}"
    fi
    
    cd ../backend || exit 1
else
    echo -e "${YELLOW}⚠️  Frontend directory not found${NC}"
fi

echo ""
echo -e "${BLUE}✨ Setup Complete!${NC}"
echo ""
echo "📝 Next Steps:"
echo ""
echo "1. Backend:"
echo "   - Verify AZURE_SPEECH_KEY and AZURE_SPEECH_REGION in .env"
echo "   - Run: python -m uvicorn main:app --reload"
echo ""
echo "2. Frontend:"
echo "   - Update VoiceAssistant.jsx with new utilities (see ENHANCEMENT_GUIDE.md)"
echo "   - Run: npm run dev"
echo ""
echo "3. Testing:"
echo "   - Test STT preprocessing: curl -X POST -F 'file=@audio.wav' http://localhost:8000/voice-input"
echo "   - Test WebSocket: ws://localhost:8000/ws/interruption"
echo "   - Test TTS: Try speaking to the assistant"
echo ""
echo -e "${GREEN}Happy voice assisting! 🎙️${NC}"
