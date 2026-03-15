import asyncio
from services.sarvam_tts_service import SarvamTextToSpeechService

async def t():
    srv = SarvamTextToSpeechService()
    try:
        ret = await srv.synthesize(text="Hello", language="od-IN")
        print("Success:", type(ret))
        print(ret[:3])
    except Exception as e:
        print("Exception:", e)
asyncio.run(t())
