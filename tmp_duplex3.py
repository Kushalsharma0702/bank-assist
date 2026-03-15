import asyncio
import websockets
import json

async def t():
    async with websockets.connect("ws://localhost:8000/ws/duplex?language=od-IN&output_language=od-IN&region=India") as ws:
        await ws.send(json.dumps({"type":"start"}))
        while True:
            msg = await ws.recv()
            if isinstance(msg, bytes):
                print(f"Received bytes of length {len(msg)}")
            else:
                print(f"Received json: {msg}")
            if isinstance(msg, str) and json.loads(msg).get("type") in ["listening", "error"]:
                break
asyncio.run(t())
