import asyncio
import websockets
import json

async def t():
    async with websockets.connect("ws://localhost:8000/ws/duplex?language=od-IN&output_language=od-IN&region=India") as ws:
        await ws.send(json.dumps({"type":"start"}))
        while True:
            msg = await ws.recv()
            print(msg)
            if json.loads(msg).get("type") == "greeting" or json.loads(msg).get("type") == "error":
                break
asyncio.run(t())
