"""Connect through the Vite dev-server proxy like a browser, subscribe, then
publish a probe event into the Redis channel and check it arrives."""
import asyncio
import json
import sys

import websockets

VITE_WS = "ws://127.0.0.1:5173/ws?token=CuPCK58QaBQoqE3aI4k822uLqnqjaGYzIODbuZ0PFpU"


async def main() -> None:
    async with websockets.connect(VITE_WS) as ws:
        hello = await asyncio.wait_for(ws.recv(), timeout=5)
        print("handshake:", hello)
        import redis.asyncio as aioredis

        r = aioredis.from_url("redis://127.0.0.1:6379/0")
        await r.publish(
            "support_hub:events",
            json.dumps({"type": "test.browser_probe", "payload": {}}),
        )
        await r.aclose()
        while True:
            frame = await asyncio.wait_for(ws.recv(), timeout=10)
            print("frame:", frame)
            if "browser_probe" in frame:
                print("RESULT: EVENT_DELIVERED_THROUGH_VITE")
                return


asyncio.run(main())
