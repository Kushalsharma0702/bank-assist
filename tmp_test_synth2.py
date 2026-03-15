import asyncio
from routers.duplex_router import _synth_to_wav_bytes

async def t():
    try:
        ret = await _synth_to_wav_bytes(text="Hello", output_language="en-US", sentence_index=0, region="Others")
        print("Success, bytes len:", len(ret))
    except Exception as e:
        print("Exception:", type(e), e)
asyncio.run(t())
