#!/bin/bash
# Quick Start Script for Banking Voice Assistant

set -e

echo "================================"
echo "🏦 Banking Voice Assistant Setup"
echo "================================"
echo ""

# Color codes
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check prerequisites
echo -e "${BLUE}Checking prerequisites...${NC}"

if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed"
    exit 1
fi
echo -e "${GREEN}✓ Python 3 found${NC}"

if ! command -v node &> /dev/null; then
    echo "❌ Node.js is not installed"
    exit 1
fi
echo -e "${GREEN}✓ Node.js found${NC}"

# Setup backend
echo ""
echo -e "${BLUE}Setting up backend...${NC}"

if [ ! -d "backend/venv" ]; then
    cd backend
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    cd ..
    echo -e "${GREEN}✓ Backend dependencies installed${NC}"
else
    echo -e "${GREEN}✓ Backend environment already exists${NC}"
fi

# Setup frontend
echo ""
echo -e "${BLUE}Setting up frontend...${NC}"

if [ ! -d "frontend/node_modules" ]; then
    cd frontend
    npm install
    cd ..
    echo -e "${GREEN}✓ Frontend dependencies installed${NC}"
else
    echo -e "${GREEN}✓ Frontend dependencies already installed${NC}"
fi

# Check .env file
echo ""
echo -e "${BLUE}Checking environment configuration...${NC}"

if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo -e "${YELLOW}⚠ Created .env from template${NC}"
        echo -e "${YELLOW}⚠ Please edit .env with your credentials!${NC}"
    else
        echo -e "${YELLOW}⚠ .env file not found${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓ .env file exists${NC}"
fi

# Display next steps
echo ""
echo -e "${GREEN}================================"
echo "✅ Setup Complete!"
echo "================================${NC}"
echo ""
echo "Next steps:"
echo ""
echo -e "${BLUE}1. Edit .env with your credentials:${NC}"
echo "   nano .env"
echo ""
echo -e "${BLUE}2. Start backend (Terminal 1):${NC}"
echo "   cd backend"
echo "   source venv/bin/activate"
echo "   python main.py"
echo ""
echo -e "${BLUE}3. Start frontend (Terminal 2):${NC}"
echo "   cd frontend"
echo "   npm run dev"
echo ""
echo -e "${BLUE}4. Open browser:${NC}"
echo "   http://localhost:5173"
echo ""
echo -e "${YELLOW}Or use Docker:${NC}"
echo "   docker-compose up --build"
echo ""
