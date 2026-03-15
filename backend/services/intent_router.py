"""
Semantic Intent Router.

Primary:  sentence-transformers/all-MiniLM-L6-v2 — cosine similarity
Fallback: Claude Sonnet (when confidence < CONFIDENCE_THRESHOLD)
"""

import asyncio
import json
import logging
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

from config import CLAUDE_MODEL_ID, get_bedrock_client
from models.intent_models import INTENT_EXAMPLES

logger = logging.getLogger("IntentRouter")

CONFIDENCE_THRESHOLD = 0.60  # below this → LLM fallback

# Intent list for Claude fallback prompt
_INTENT_LIST = ", ".join(INTENT_EXAMPLES.keys())


class SemanticIntentRouter:
    """
    Encodes all intent examples once at startup, then uses cosine similarity
    to classify new messages in <50 ms.  Falls back to Claude when uncertain.
    """

    def __init__(self):
        logger.info("Loading sentence-transformers model (all-MiniLM-L6-v2)…")
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer("all-MiniLM-L6-v2")
        except ImportError:
            raise RuntimeError(
                "sentence-transformers not installed. "
                "Run: pip install sentence-transformers"
            )

        # Pre-encode all examples
        self._intents: List[str] = []
        self._phrases: List[str] = []
        all_phrases: List[str] = []

        for intent, examples in INTENT_EXAMPLES.items():
            for phrase in examples:
                self._intents.append(intent)
                self._phrases.append(phrase)
                all_phrases.append(phrase)

        logger.info(f"Encoding {len(all_phrases)} intent phrases…")
        raw = self._model.encode(all_phrases, convert_to_numpy=True, normalize_embeddings=True)
        self._embeddings: np.ndarray = raw  # shape (N, D), already L2-normalised

        logger.info("✅ Intent router ready")

        # Bedrock client for LLM fallback
        self._bedrock = get_bedrock_client()

    def _cosine_route(self, text: str) -> Tuple[str, float, str]:
        """Return (intent, confidence, matched_phrase) via cosine similarity."""
        query_emb = self._model.encode([text], convert_to_numpy=True, normalize_embeddings=True)
        # cosine similarity = dot product when vectors are unit-normalised
        sims = (self._embeddings @ query_emb.T).flatten()
        best_idx = int(np.argmax(sims))
        return self._intents[best_idx], float(sims[best_idx]), self._phrases[best_idx]

    def route_fast(self, text: str) -> Tuple[str, float, str]:
        """
        Cosine-only intent prediction — no LLM fallback, no I/O.
        Runs in ~20 ms and is safe to call from any thread.
        Used to warm up the intent cache while the user is still speaking.
        """
        return self._cosine_route(text)

    def _llm_route(self, text: str) -> Tuple[str, float, str]:
        """Fallback: ask Claude to classify the intent."""
        system = (
            "You are a banking intent classifier. "
            f"Classify the message into ONE of: {_INTENT_LIST}. "
            'Return ONLY valid JSON: {"intent":"...","confidence":0.0,"reasoning":"..."}'
        )
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 200,
            "temperature": 0.0,
            "system": system,
            "messages": [{"role": "user", "content": f"Message: {text}"}],
        }
        try:
            resp = self._bedrock.invoke_model(
                modelId=CLAUDE_MODEL_ID, body=json.dumps(body)
            )
            raw = json.loads(resp["body"].read())
            text_out = raw.get("content", [{}])[0].get("text", "").strip()
            for marker in ("```json", "```"):
                if marker in text_out:
                    text_out = text_out.split(marker)[-1].split("```")[0].strip()
            parsed = json.loads(text_out)
            intent = parsed.get("intent", "UNKNOWN")
            if intent not in INTENT_EXAMPLES:
                intent = "UNKNOWN"
            return intent, float(parsed.get("confidence", 0.5)), "llm_classification"
        except Exception as exc:
            logger.error(f"LLM fallback failed: {exc}")
            return "UNKNOWN", 0.0, "error"

    def route_fast(self, text: str) -> Tuple[str, float, str]:
        """
        Cosine-only intent prediction — no LLM fallback, no I/O, ~20 ms.
        Thread-safe. Used to warm up the intent cache while the user is
        still speaking so the result is ready before the final transcript.
        """
        return self._cosine_route(text)

    async def route(self, text: str) -> Tuple[str, float, str, str, float]:
        """
        Classify intent for the given (English) text.

        Returns:
            (intent, confidence, matched_phrase, method, latency_ms)
            method: "semantic" | "llm_fallback"
        """
        t0 = time.perf_counter()
        intent, confidence, matched_phrase = self._cosine_route(text)
        method = "semantic"

        if confidence < CONFIDENCE_THRESHOLD:
            logger.info(
                f"Semantic confidence {confidence:.2f} < {CONFIDENCE_THRESHOLD}, "
                "falling back to Claude…"
            )
            loop = asyncio.get_event_loop()
            try:
                intent, confidence, matched_phrase = await asyncio.wait_for(
                    loop.run_in_executor(None, self._llm_route, text),
                    timeout=4.0,
                )
                method = "llm_fallback"
            except asyncio.TimeoutError:
                logger.warning(
                    f"⏰ LLM fallback timed out (>4 s) — using cosine result: "
                    f"{intent} ({confidence:.2f})"
                )
                method = "timeout_cosine"
                # intent/confidence/matched_phrase remain the cosine-only values

        latency_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            f"✅ Intent: {intent}  confidence={confidence:.2f}  "
            f"method={method}  [{latency_ms:.0f}ms]"
        )
        return intent, confidence, matched_phrase, method, latency_ms


# Singleton — loaded once at app startup
_router_instance: Optional[SemanticIntentRouter] = None


def get_intent_router() -> SemanticIntentRouter:
    global _router_instance
    if _router_instance is None:
        _router_instance = SemanticIntentRouter()
    return _router_instance
