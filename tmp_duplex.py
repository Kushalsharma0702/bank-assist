import asyncio
import websockets
import json

async def t():
    async with websockets.connect("ws://localhost:8000/ws/duplex?language=od-IN&output_language=od-IN&region=India") as ws:
        msg = await ws.recv()
        print(msg)
asyncio.run(t())
