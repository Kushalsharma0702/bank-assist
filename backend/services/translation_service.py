"""
Translation service.

Primary:  Azure Translator REST API
Fallback: Claude via AWS Bedrock (if Azure fails or key not set)
"""

import json
import logging
import os
import time
from typing import Tuple

import httpx

from config import (
    AZURE_TRANSLATOR_ENDPOINT,
    AZURE_TRANSLATOR_KEY,
    AZURE_TRANSLATOR_REGION,
    CLAUDE_MODEL_ID,
    get_bedrock_client,
)
from models.intent_models import LANGUAGE_CONFIG

logger = logging.getLogger("TranslationService")

_TRANSLATOR_BASE = (
    AZURE_TRANSLATOR_ENDPOINT.rstrip("/")
    if AZURE_TRANSLATOR_ENDPOINT
    else "https://api.cognitive.microsofttranslator.com"
)


def _azure_translate(text: str, to_lang: str, from_lang: str = "") -> str:
    """Call Azure Translator REST API.  Returns translated text or raises."""
    if not AZURE_TRANSLATOR_KEY:
        raise RuntimeError("AZURE_TRANSLATOR_KEY not set")

    params = {"api-version": "3.0", "to": to_lang}
    if from_lang:
        params["from"] = from_lang

    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_TRANSLATOR_KEY,
        "Ocp-Apim-Subscription-Region": AZURE_TRANSLATOR_REGION,
        "Content-Type": "application/json",
    }
    resp = httpx.post(
        f"{_TRANSLATOR_BASE}/translate",
        params=params,
        headers=headers,
        json=[{"Text": text}],
        timeout=10.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return data[0]["translations"][0]["text"]


def _claude_translate(text: str, target_language_name: str, source_language_name: str) -> str:
    """Fallback translation via Claude (Bedrock)."""
    client = get_bedrock_client()
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 200,  # banking responses are short; 200 tokens is ample
        "temperature": 0.1,
        "system": (
            f"You are a professional {source_language_name}-to-{target_language_name} translator "
            "specialising in banking and finance. "
            "Return ONLY the translated text, no explanations."
        ),
        "messages": [
            {"role": "user", "content": f"Translate to {target_language_name}:\n\n{text}"}
        ],
    }
    resp = client.invoke_model(modelId=CLAUDE_MODEL_ID, body=json.dumps(body))
    content = json.loads(resp["body"].read()).get("content", [])
    return content[0].get("text", "").strip() if content else text


class TranslationService:
    """Translate between any supported language and English, or to Khmer."""

    async def translate_to_khmer(self, text: str) -> Tuple[str, float]:
        """
        Translate English text to Khmer (km-KH) — always used before Khmer TTS.

        Returns:
            (khmer_text, latency_ms)
        """
        t0 = time.perf_counter()
        translated = ""
        try:
            translated = _azure_translate(text, to_lang="km", from_lang="en")
            logger.info(f"✅ Translated → Khmer: {translated[:80]!r}")
        except Exception as azure_err:
            logger.warning(f"Azure Translator (→Khmer) failed ({azure_err}), using Claude fallback")
            try:
                translated = _claude_translate(text, "Khmer", "English")
                logger.info(f"✅ Claude fallback → Khmer: {translated[:80]!r}")
            except Exception as claude_err:
                logger.error(f"Claude fallback (→Khmer) also failed: {claude_err}")
                translated = text

        latency_ms = (time.perf_counter() - t0) * 1000
        return translated, latency_ms

    async def translate_to_english(
        self, text: str, source_language: str
    ) -> Tuple[str, float]:
        """
        Translate text to English.

        Returns:
            (english_text, latency_ms)
        """
        if source_language == "en-US":
            return text, 0.0

        t0 = time.perf_counter()
        lang_cfg = LANGUAGE_CONFIG.get(source_language, LANGUAGE_CONFIG["en-US"])
        src_code = lang_cfg["translator_code"]
        src_name = lang_cfg["name"]

        translated = ""
        try:
            translated = _azure_translate(text, to_lang="en", from_lang=src_code)
            logger.info(f"✅ Azure Translator ({src_name}→EN): {translated!r}")
        except Exception as azure_err:
            logger.warning(f"Azure Translator failed ({azure_err}), using Claude fallback")
            try:
                translated = _claude_translate(text, "English", src_name)
                logger.info(f"✅ Claude fallback ({src_name}→EN): {translated!r}")
            except Exception as claude_err:
                logger.error(f"Claude fallback also failed: {claude_err}")
                translated = text

        latency_ms = (time.perf_counter() - t0) * 1000
        return translated, latency_ms

    async def translate_to_language(
        self, text: str, target_language: str
    ) -> Tuple[str, float]:
        """
        Translate English text to the given target language.

        Returns:
            (translated_text, latency_ms)
        """
        if target_language == "en-US":
            return text, 0.0

        t0 = time.perf_counter()
        lang_cfg = LANGUAGE_CONFIG.get(target_language, LANGUAGE_CONFIG["en-US"])
        tgt_code = lang_cfg["translator_code"]
        tgt_name = lang_cfg["name"]

        translated = ""
        try:
            translated = _azure_translate(text, to_lang=tgt_code, from_lang="en")
            logger.info(f"✅ Azure Translator (EN→{tgt_name}): {translated[:80]!r}")
        except Exception as azure_err:
            logger.warning(f"Azure Translator failed ({azure_err}), using Claude fallback")
            try:
                translated = _claude_translate(text, tgt_name, "English")
                logger.info(f"✅ Claude fallback (EN→{tgt_name}): {translated[:80]!r}")
            except Exception as claude_err:
                logger.error(f"Claude fallback also failed: {claude_err}")
                translated = text

        latency_ms = (time.perf_counter() - t0) * 1000
        return translated, latency_ms
