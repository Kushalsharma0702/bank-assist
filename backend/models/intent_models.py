"""
Intent dataset, language config and Pydantic models.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel

# ============================================================================
# LANGUAGE CONFIG
# ============================================================================

LANGUAGE_CONFIG: Dict[str, Dict] = {
    "ar-SA": {"name": "Arabic (Saudi Arabia)", "flag": "🇸🇦", "tts_voice": "ar-SA-ZariyahNeural", "translator_code": "ar", "auto_detect_candidates": ["ar-SA", "en-US"]},
    "bn-BD": {"name": "Bengali (Bangladesh)", "flag": "🇧🇩", "tts_voice": "bn-BD-NabanitaNeural", "translator_code": "bn", "auto_detect_candidates": ["bn-BD", "en-US"]},
    "de-DE": {"name": "German", "flag": "🇩🇪", "tts_voice": "de-DE-KatjaNeural", "translator_code": "de", "auto_detect_candidates": ["de-DE", "en-US"]},
    "en-US": {"name": "English", "flag": "🇺🇸", "tts_voice": "en-US-JennyNeural", "translator_code": "en", "auto_detect_candidates": ["en-US"]},
    "es-ES": {"name": "Spanish (Spain)", "flag": "🇪🇸", "tts_voice": "es-ES-ElviraNeural", "translator_code": "es", "auto_detect_candidates": ["es-ES", "en-US"]},
    "fil-PH": {"name": "Filipino", "flag": "🇵🇭", "tts_voice": "fil-PH-BlessicaNeural", "translator_code": "tl", "auto_detect_candidates": ["fil-PH", "en-US"]},
    "fr-FR": {"name": "French", "flag": "🇫🇷", "tts_voice": "fr-FR-DeniseNeural", "translator_code": "fr", "auto_detect_candidates": ["fr-FR", "en-US"]},
    "hi-IN": {"name": "Hindi", "flag": "🇮🇳", "tts_voice": "hi-IN-SwaraNeural", "translator_code": "hi", "auto_detect_candidates": ["hi-IN", "en-US"]},
    "bn-IN": {"name": "Bengali (India)", "flag": "🇮🇳", "tts_voice": "bn-IN-TanishaaNeural", "translator_code": "bn", "auto_detect_candidates": ["bn-IN", "en-US"]},
    "gu-IN": {"name": "Gujarati", "flag": "🇮🇳", "tts_voice": "gu-IN-DhwaniNeural", "translator_code": "gu", "auto_detect_candidates": ["gu-IN", "en-US"]},
    "kn-IN": {"name": "Kannada", "flag": "🇮🇳", "tts_voice": "kn-IN-SapnaNeural", "translator_code": "kn", "auto_detect_candidates": ["kn-IN", "en-US"]},
    "ml-IN": {"name": "Malayalam", "flag": "🇮🇳", "tts_voice": "ml-IN-SobhanaNeural", "translator_code": "ml", "auto_detect_candidates": ["ml-IN", "en-US"]},
    "mr-IN": {"name": "Marathi", "flag": "🇮🇳", "tts_voice": "mr-IN-AarohiNeural", "translator_code": "mr", "auto_detect_candidates": ["mr-IN", "en-US"]},
    "od-IN": {"name": "Odia", "flag": "🇮🇳", "tts_voice": "od-IN-SushriNeural", "translator_code": "or", "auto_detect_candidates": ["od-IN", "en-US"]},
    "pa-IN": {"name": "Punjabi", "flag": "🇮🇳", "tts_voice": "pa-IN-OjasNeural", "translator_code": "pa", "auto_detect_candidates": ["pa-IN", "en-US"]},
    "id-ID": {"name": "Indonesian", "flag": "🇮🇩", "tts_voice": "id-ID-GadisNeural", "translator_code": "id", "auto_detect_candidates": ["id-ID", "en-US"]},
    "it-IT": {"name": "Italian", "flag": "🇮🇹", "tts_voice": "it-IT-ElsaNeural", "translator_code": "it", "auto_detect_candidates": ["it-IT", "en-US"]},
    "ja-JP": {"name": "Japanese", "flag": "🇯🇵", "tts_voice": "ja-JP-NanamiNeural", "translator_code": "ja", "auto_detect_candidates": ["ja-JP", "en-US"]},
    "km-KH": {"name": "Khmer", "flag": "🇰🇭", "tts_voice": "km-KH-PisethNeural", "translator_code": "km", "auto_detect_candidates": ["km-KH", "en-US"]},
    "ko-KR": {"name": "Korean", "flag": "🇰🇷", "tts_voice": "ko-KR-SunHiNeural", "translator_code": "ko", "auto_detect_candidates": ["ko-KR", "en-US"]},
    "ms-MY": {"name": "Malay", "flag": "🇲🇾", "tts_voice": "ms-MY-YasminNeural", "translator_code": "ms", "auto_detect_candidates": ["ms-MY", "en-US"]},
    "nl-NL": {"name": "Dutch", "flag": "🇳🇱", "tts_voice": "nl-NL-ColetteNeural", "translator_code": "nl", "auto_detect_candidates": ["nl-NL", "en-US"]},
    "pl-PL": {"name": "Polish", "flag": "🇵🇱", "tts_voice": "pl-PL-ZofiaNeural", "translator_code": "pl", "auto_detect_candidates": ["pl-PL", "en-US"]},
    "pt-BR": {"name": "Portuguese (Brazil)", "flag": "🇧🇷", "tts_voice": "pt-BR-FranciscaNeural", "translator_code": "pt", "auto_detect_candidates": ["pt-BR", "en-US"]},
    "ru-RU": {"name": "Russian", "flag": "🇷🇺", "tts_voice": "ru-RU-SvetlanaNeural", "translator_code": "ru", "auto_detect_candidates": ["ru-RU", "en-US"]},
    "si-LK": {"name": "Sinhala", "flag": "🇱🇰", "tts_voice": "si-LK-ThiliniNeural", "translator_code": "si", "auto_detect_candidates": ["si-LK", "en-US"]},
    "sv-SE": {"name": "Swedish", "flag": "🇸🇪", "tts_voice": "sv-SE-SofieNeural", "translator_code": "sv", "auto_detect_candidates": ["sv-SE", "en-US"]},
    "ta-IN": {"name": "Tamil (India)", "flag": "🇮🇳", "tts_voice": "ta-IN-PallaviNeural", "translator_code": "ta", "auto_detect_candidates": ["ta-IN", "en-US"]},
    "ta-LK": {"name": "Tamil (Sri Lanka)", "flag": "🇱🇰", "tts_voice": "ta-LK-SaranyaNeural", "translator_code": "ta", "auto_detect_candidates": ["ta-LK", "en-US"]},
    "te-IN": {"name": "Telugu", "flag": "🇮🇳", "tts_voice": "te-IN-ShrutiNeural", "translator_code": "te", "auto_detect_candidates": ["te-IN", "en-US"]},
    "th-TH": {"name": "Thai", "flag": "🇹🇭", "tts_voice": "th-TH-PremwadeeNeural", "translator_code": "th", "auto_detect_candidates": ["th-TH", "en-US"]},
    "tr-TR": {"name": "Turkish", "flag": "🇹🇷", "tts_voice": "tr-TR-EmelNeural", "translator_code": "tr", "auto_detect_candidates": ["tr-TR", "en-US"]},
    "uk-UA": {"name": "Ukrainian", "flag": "🇺🇦", "tts_voice": "uk-UA-PolinaNeural", "translator_code": "uk", "auto_detect_candidates": ["uk-UA", "en-US"]},
    "ur-PK": {"name": "Urdu", "flag": "🇵🇰", "tts_voice": "ur-PK-UzmaNeural", "translator_code": "ur", "auto_detect_candidates": ["ur-PK", "en-US"]},
    "vi-VN": {"name": "Vietnamese", "flag": "🇻🇳", "tts_voice": "vi-VN-HoaiMyNeural", "translator_code": "vi", "auto_detect_candidates": ["vi-VN", "en-US"]},
    "zh-CN": {"name": "Chinese (Simplified)", "flag": "🇨🇳", "tts_voice": "zh-CN-XiaoxiaoNeural", "translator_code": "zh-Hans", "auto_detect_candidates": ["zh-CN", "en-US"]},
    "zh-HK": {"name": "Chinese (Hong Kong)", "flag": "🇭🇰", "tts_voice": "zh-HK-HiuMaanNeural", "translator_code": "zh-Hant", "auto_detect_candidates": ["zh-HK", "en-US"]},
    "zh-TW": {"name": "Chinese (Traditional)", "flag": "🇹🇼", "tts_voice": "zh-TW-HsiaoChenNeural", "translator_code": "zh-Hant", "auto_detect_candidates": ["zh-TW", "en-US"]},
}

SUPPORTED_LANGUAGES = set(LANGUAGE_CONFIG.keys())

# ============================================================================
# INTENT DATASET  (17 intents, 8-10 English example phrases each)
# These are encoded at startup for semantic similarity matching.
# ============================================================================

INTENT_EXAMPLES: Dict[str, List[str]] = {
    "GREETING": [
        "hello",
        "hi",
        "good morning",
        "good afternoon",
        "good evening",
        "hey there",
        "how are you",
        "I want to say hello",
        "hi I need help",
        "good day",
    ],
    "BALANCE": [
        "what is my balance",
        "check my account balance",
        "how much do I have in my account",
        "tell me my account balance",
        "show my account balance",
        "what is my current account balance",
        "I want to know my balance",
        "balance inquiry",
        "current account balance",
        "how much money is in my account",
        "check my savings balance",
        "what is my available balance",
        "how much funds do I have",
    ],
    "STATEMENT": [
        "I need my statement",
        "send me my bank statement",
        "account statement",
        "show my transactions",
        "transaction history",
        "last month statement",
        "mini statement",
        "I want to see my statement",
        "email my statement",
        "download account statement",
    ],
    "CARD_BLOCK": [
        "block my card",
        "my card is lost",
        "card stolen",
        "freeze my card",
        "disable my credit card",
        "I lost my debit card",
        "cancel my card",
        "my card is missing I want to block it",
        "block debit card immediately",
        "I want to freeze my card",
    ],
    "TX_DISPUTE": [
        "I did not make this transaction",
        "unauthorized charge on my account",
        "wrong transaction",
        "dispute a charge",
        "I was charged twice",
        "fraudulent transaction",
        "this debit was not mine",
        "I want to dispute a payment",
        "unknown charge on my statement",
        "charge I do not recognize",
    ],
    "KYC_STATUS": [
        "KYC status",
        "my KYC is pending",
        "when will KYC be complete",
        "KYC verification",
        "I submitted KYC documents",
        "KYC approval status",
        "is my KYC done",
        "check KYC status",
        "KYC not approved yet",
        "update my KYC",
    ],
    "EMI_DUE": [
        "when is my EMI due",
        "EMI due date",
        "how much is my EMI",
        "next EMI payment date",
        "loan installment due",
        "monthly payment amount",
        "when should I pay my loan",
        "EMI reminder",
        "my loan payment schedule",
        "how much do I owe this month",
        "check my loan details",
        "what is my loan plan",
        "show me my loan plan",
        "I want to check my loan plan",
        "loan plan information",
        "latest loan plan",
        "what loan plan am I on",
        "loan interest rate",
        "what is the interest on my loan",
        "show my current loan details",
        "loan repayment plan",
        "what are the best loan options",
        "good loan plan available",
        "I want to check the latest loan plan",
        "tell me about my loan",
    ],
    "FORECLOSURE": [
        "close my loan",
        "foreclose my loan",
        "pay off entire loan",
        "loan closure",
        "I want to prepay my loan",
        "full loan settlement",
        "loan foreclosure charges",
        "close loan account",
        "prepayment penalty",
        "I want to pay off my loan completely",
    ],
    "ADDRESS_CHANGE": [
        "change my address",
        "update address",
        "new address",
        "I moved",
        "update my residential address",
        "address update request",
        "I want to change my registered address",
        "new home address",
        "address correction needed",
        "update my mailing address",
    ],
    "COLLECTIONS_PTP": [
        "I will pay by Friday",
        "promise to pay",
        "I will pay next week",
        "I can pay on the 15th",
        "I will make payment soon",
        "give me until Monday",
        "I will settle by end of month",
        "I promise I will pay",
        "I will pay after my salary",
        "I commit to making the payment",
    ],
    "COLLECTIONS_PAYLINK": [
        "send me a payment link",
        "I want to pay online",
        "send payment URL",
        "I need a link to pay",
        "WhatsApp payment link",
        "send me a link to make payment",
        "can you send payment link on SMS",
        "I want to pay via link",
        "share payment portal link",
        "online payment link please",
    ],
    "PAYMENT_DIFFICULTY": [
        "I cannot pay",
        "I am struggling financially",
        "I lost my job",
        "financial hardship",
        "I cannot afford the EMI",
        "I have money problems",
        "I am unable to make payment",
        "I have no money right now",
        "I am in financial difficulty",
        "I cannot pay this month",
    ],
    "CALLBACK": [
        "call me back",
        "I want a callback",
        "please call me later",
        "schedule a call",
        "call me tomorrow",
        "I want someone to call me",
        "can you call me at 5pm",
        "please call back",
        "I need a return call",
        "arrange a callback for me",
    ],
    "REQUEST_AGENT": [
        "I want to speak to a human",
        "transfer to agent",
        "speak to customer service",
        "I need a real person",
        "connect me to support",
        "human agent please",
        "I want to talk to someone",
        "transfer the call",
        "speak to a manager",
        "get me a live agent",
    ],
    "THANKS": [
        "thank you",
        "thanks a lot",
        "that was helpful",
        "you are great",
        "appreciated",
        "perfect thanks",
        "that is all I needed",
        "bye thank you",
        "great help",
        "thank you very much",
    ],
    "PARTIAL_PAYMENT": [
        "I can pay half",
        "I can pay partially",
        "I can pay some amount",
        "I cannot pay the full EMI",
        "I will pay part of the loan",
        "partial payment",
        "I can only pay some",
        "I can only pay a portion of the amount",
        "I will pay half the amount",
        "partial settlement",
    ],
    "FULL_PAYMENT": [
        "I will pay the full EMI",
        "I will clear everything",
        "I will pay the full amount tomorrow",
        "full payment",
        "complete payment",
        "I want to pay everything",
        "I will settle the entire amount",
        "full settlement",
        "pay all outstanding dues",
        "I will pay the total amount due",
    ],
}

# ============================================================================
# WORKFLOW CONFIG  (maps intent → suggested action + metadata)
# ============================================================================

WORKFLOW_CONFIG: Dict[str, Dict[str, Any]] = {
    "GREETING":            {"action": "greet",             "escalate": False, "send_paylink": False},
    "BALANCE":             {"action": "balance_inquiry",   "escalate": False, "send_paylink": False},
    "STATEMENT":           {"action": "send_statement",    "escalate": False, "send_paylink": False},
    "CARD_BLOCK":          {"action": "block_card",        "escalate": False, "send_paylink": False},
    "TX_DISPUTE":          {"action": "raise_dispute",     "escalate": False, "send_paylink": False},
    "KYC_STATUS":          {"action": "check_kyc",         "escalate": False, "send_paylink": False},
    "EMI_DUE":             {"action": "emi_inquiry",       "escalate": False, "send_paylink": False},
    "FORECLOSURE":         {"action": "foreclosure_info",  "escalate": False, "send_paylink": False},
    "ADDRESS_CHANGE":      {"action": "update_address",    "escalate": False, "send_paylink": False},
    "COLLECTIONS_PTP":     {"action": "record_ptp",        "escalate": False, "send_paylink": False},
    "COLLECTIONS_PAYLINK": {"action": "send_paylink",      "escalate": False, "send_paylink": True},
    "PAYMENT_DIFFICULTY":  {"action": "hardship_program",  "escalate": True,  "send_paylink": False},
    "CALLBACK":            {"action": "schedule_callback", "escalate": False, "send_paylink": False},
    "REQUEST_AGENT":       {"action": "transfer_agent",    "escalate": True,  "send_paylink": False},
    "THANKS":              {"action": "farewell",          "escalate": False, "send_paylink": False},
    "PARTIAL_PAYMENT":     {"action": "partial_payment",   "escalate": False, "send_paylink": True},
    "FULL_PAYMENT":        {"action": "full_payment",      "escalate": False, "send_paylink": True},
}

# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class PipelineStage(BaseModel):
    name:          str
    icon:          str
    status:        str            # "pending" | "running" | "done" | "error"
    latency_ms:    Optional[float] = None
    output:        Optional[str]  = None
    confidence:    Optional[float] = None
    matched_phrase: Optional[str] = None


class PipelineResult(BaseModel):
    # Language context
    language:             str   # user-selected language (drives TTS)
    detected_language:    str   # language Azure STT detected in audio
    native_language_name: str
    # Transcript
    transcript:           str   # original transcript (in detected language)
    english_translation:  str   # transcript translated to English for reasoning
    # Intent
    intent:               str
    matched_phrase:       str
    confidence:           float
    intent_method:        str
    # Workflow
    workflow_action:      str
    escalate:             bool
    send_paylink:         bool
    # Responses
    response_en:          str   # Claude response in English
    response_native:      str   # response translated to user-selected language
    response_khmer:       str   # response translated to Khmer (always populated)
    # Audio
    tts_audio_url:        str
    tts_audio_base64:     str
    tts_voice:            str   # actual voice used for synthesis
    # Meta
    processing_time:      float
    pipeline_stages:      List[PipelineStage]
    no_speech:            bool = False


class TextInputRequest(BaseModel):
    text:     str
    language: str = "km-KH"
    region:   str = "Others"
