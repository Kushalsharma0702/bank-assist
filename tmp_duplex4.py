import asyncio
import websockets
import json

async def t():
    async with websockets.connect("ws://localhost:8000/ws/duplex?language=en-US&output_language=en-US&region=Others") as ws:
        await ws.send(json.dumps({"type":"start"}))
        await ws.send(b"\x00" * 4096)
        while True:
            msg = await ws.recv()
            if isinstance(msg, bytes):
                print(f"Received bytes of length {len(msg)}")
                break
            else:
                print(f"Received json: {msg}")
asyncio.run(t())
