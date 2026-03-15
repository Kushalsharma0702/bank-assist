import asyncio
import base64
from routers.duplex_router import _synth_to_wav_bytes

async def t():
    try:
        ret = await _synth_to_wav_bytes(text="Hello", output_language="od-IN", sentence_index=0, region="India")
        print("Success, bytes len:", len(ret))
    except Exception as e:
        print("Exception:", e)
asyncio.run(t())
