import redis
from redis.asyncio import Redis

pool = redis.ConnectionPool(
    host="localhost",
    port=6379,
    max_connections=50,
    decode_responses=True,
)

AppRedis = redis.Redis(connection_pool=pool)

async_pool = redis.asyncio.ConnectionPool(
    host="localhost",
    port=6379,
    max_connections=50,
    decode_responses=True,
)
AppRedisAsync = Redis(connection_pool=async_pool)
