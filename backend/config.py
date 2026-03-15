"""
Centralised configuration — reads from environment / .env file.

Boto3 credential resolution order (standard AWS chain):
  1. Environment variables (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY)  ← local dev
  2. EC2 instance profile / ECS task role / App Runner instance role     ← AWS deploy
  3. ~/.aws/credentials                                                   ← local dev
Never hard-code credentials; just leave the env vars empty when deploying
to AWS and attach the correct IAM role to the service instead.
"""

import os
import boto3
from dotenv import load_dotenv

load_dotenv()

# ── Azure Speech ──────────────────────────────────────────────────────────────
AZURE_SPEECH_KEY    = os.getenv("AZURE_SPEECH_KEY", "")
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION", "southeastasia")

# ── Sarvam Speech ─────────────────────────────────────────────────────────────
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
SARVAM_STT_MODEL = os.getenv("SARVAM_STT_MODEL", "saaras:v3")
SARVAM_TTS_MODEL = os.getenv("SARVAM_TTS_MODEL", "bulbul:v3")
SARVAM_TTS_SPEAKER = os.getenv("SARVAM_TTS_SPEAKER", "shubh")
SARVAM_STT_STREAMING_URL = os.getenv("SARVAM_STT_STREAMING_URL", "wss://api.sarvam.ai/speech-to-text/ws")
SARVAM_TTS_STREAMING_URL = os.getenv("SARVAM_TTS_STREAMING_URL", "wss://api.sarvam.ai/text-to-speech/ws")

# ── Azure Translator ──────────────────────────────────────────────────────────
AZURE_TRANSLATOR_KEY      = os.getenv("AZURE_TRANSLATOR_KEY", "")
AZURE_TRANSLATOR_REGION   = os.getenv("AZURE_TRANSLATOR_REGION", "southeastasia")
AZURE_TRANSLATOR_ENDPOINT = os.getenv(
    "AZURE_TRANSLATOR_ENDPOINT",
    "https://api.cognitive.microsofttranslator.com",
)

# ── AWS / Bedrock ─────────────────────────────────────────────────────────────
AWS_REGION            = os.getenv("AWS_REGION", "ap-southeast-1")
AWS_ACCESS_KEY_ID     = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
CLAUDE_MODEL_ID       = os.getenv(
    "CLAUDE_MODEL_ID",
    "anthropic.claude-3-5-sonnet-20240620-v1:0",
)


def get_bedrock_client():
    """
    Return a boto3 bedrock-runtime client.

    When running locally with an .env file, uses explicit credentials.
    When running on AWS (App Runner / ECS / EC2), uses the attached IAM role
    automatically via the standard boto3 credential chain — no secrets needed
    in the environment.
    """
    kwargs: dict = {"region_name": AWS_REGION}
    if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
        kwargs["aws_access_key_id"]     = AWS_ACCESS_KEY_ID
        kwargs["aws_secret_access_key"] = AWS_SECRET_ACCESS_KEY
    return boto3.client("bedrock-runtime", **kwargs)
