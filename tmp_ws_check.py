import asyncio
import json
import websockets

async def main():
    uri = "ws://localhost:8000/ws/conversation?language=en-US&output_language=en-US"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"type": "start"}))
        msg = await ws.recv()
        print(msg)

asyncio.run(main())
