"""
Banking Voice Agent — FastAPI entry point.

Architecture:
  services/   — STT, Translation, Intent Router, Workflow, Response, TTS
  core/        — Pipeline Orchestrator
  routers/     — HTTP routes
  models/      — Intent dataset + Pydantic schemas
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from models.intent_models import LANGUAGE_CONFIG

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("BankingVoiceAgent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Pre-load the sentence-transformers model at startup."""
    logger.info("=" * 72)
    logger.info("🚀 Banking Voice Agent starting up…")
    logger.info(f"   Languages: {', '.join(LANGUAGE_CONFIG.keys())}")
    logger.info("=" * 72)

    logger.info("\u23ed Intent router preloading at startup…")
    from services.intent_router import get_intent_router
    get_intent_router()   # loads + encodes model once
    logger.info("\u2705 Intent router ready (preloaded)")

    yield

    logger.info("Banking Voice Agent shut down.")


app = FastAPI(
    title="Banking Voice Agent API",
    description="Production-grade multilingual banking voice AI",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from routers.voice_router import router
from routers.interruption_ws import router as ws_router
from routers.conversation_router import router as conversation_router
from routers.duplex_router import router as duplex_router
app.include_router(router)
app.include_router(ws_router)
app.include_router(conversation_router)
app.include_router(duplex_router)


@app.get("/")
async def root():
    return {
        "service": "Banking Voice Agent API",
        "version": "3.0.0",
        "pipeline": "STT → Translation → Semantic Intent → Workflow → Claude Sonnet → TTS",
        "supported_languages": list(LANGUAGE_CONFIG.keys()),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
