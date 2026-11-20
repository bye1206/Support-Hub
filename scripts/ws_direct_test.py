"""Direct backend WS test (bypasses Vite): consume ready, publish a probe
into the events channel, verify it arrives on the websocket."""
import asyncio
import json

import redis.asyncio as aioredis
import websockets

WS = "ws://127.0.0.1:8000/ws?token=CuPCK58QaBQoqE3aI4k822uLqnqjaGYzIODbuZ0PFpU"


async def main() -> None:
    async with websockets.connect(WS) as ws:
        ready = await asyncio.wait_for(ws.recv(), timeout=5)
        print("handshake:", ready)
        r = aioredis.from_url("redis://127.0.0.1:6379/0")
        await r.publish(
            "support_hub:events",
            json.dumps({"type": "test.direct_probe", "payload": {}}),
        )
        await r.aclose()
        print("published, waiting for frame...")
        for _ in range(3):
            frame = await asyncio.wait_for(ws.recv(), timeout=10)
            print("frame:", frame)
            if "direct_probe" in frame:
                print("RESULT: BACKEND_WS_OK")
                return


asyncio.run(main())
