import os
import sys
import pytest
from httpx import AsyncClient, ASGITransport

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from main import app
from core.pipeline_orchestrator import PipelineOrchestrator

@pytest.mark.asyncio
async def test_text_input_azure_others():
    """Test text input pipeline for Others region (Azure)."""
    # Skip if Azure key not available to avoid C++ invalid arg errors on empty keys
    from config import AZURE_SPEECH_KEY
    if not AZURE_SPEECH_KEY:
        pytest.skip("AZURE_SPEECH_KEY is not set.")
        
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post(
            "/text-input",
            json={
                "text": "Hello, how are you?",
                "language": "en-US",
                "region": "Others"
            }
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert "response_native" in data
        assert "tts_audio_url" in data
        assert "intent" in data
        
@pytest.mark.asyncio
async def test_text_input_sarvam_india():
    """Test text input pipeline for India region (Sarvam)."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.post(
            "/text-input",
            json={
                "text": "नमस्ते, आप कैसे हैं?",
                "language": "hi-IN",
                "region": "India"
            }
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        assert "response_native" in data
        assert "tts_audio_url" in data
        assert "intent" in data

@pytest.mark.asyncio
async def test_orchestrator_engine_routing():
    """Unit test for orchestrator dynamic property engine routing."""
    orchestrator = PipelineOrchestrator()
    
    # Should route to Azure for Others
    stt_provider_others = orchestrator._get_stt_service("Others")
    assert stt_provider_others.__class__.__name__ == "SpeechToTextService"
    
    tts_provider_others = orchestrator._get_tts_service("Others")
    assert tts_provider_others.__class__.__name__ == "TextToSpeechService"
    
    # Should route to Sarvam for India
    stt_provider_india = orchestrator._get_stt_service("India")
    assert stt_provider_india.__class__.__name__ == "SarvamSpeechToTextService"
    
    tts_provider_india = orchestrator._get_tts_service("India")
    assert tts_provider_india.__class__.__name__ == "SarvamTextToSpeechService"
    
    # Defaults
    assert orchestrator._normalize_region("") == "Others"
    assert orchestrator._normalize_region("unknown") == "Others"
    assert orchestrator._normalize_region("india") == "India"
