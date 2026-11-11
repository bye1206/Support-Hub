import asyncio

from app.infra.redis_client import RedisClient


async def main() -> None:
    r = RedisClient("redis://127.0.0.1:6379/0")
    await r.set_string("support_hub:session:probe123", '{"operator_id":"x"}', 60)
    got = await r.get_string("support_hub:session:probe123")
    print("get:", got)
    await r.delete_key("support_hub:session:probe123")
    await r.close()


asyncio.run(main())
