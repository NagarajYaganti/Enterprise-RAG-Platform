from arq import ArqRedis, create_pool
from arq.connections import RedisSettings
from arq.jobs import Job
from pydantic_settings import BaseSettings, SettingsConfigDict

EMBED_QUEUE_NAME = "arq:embed_queue"


class QueueSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    redis_host: str = "localhost"
    redis_port: int = 6379


def get_redis_settings(settings: QueueSettings | None = None) -> RedisSettings:
    settings = settings or QueueSettings()
    return RedisSettings(host=settings.redis_host, port=settings.redis_port)


async def get_redis_pool(settings: QueueSettings | None = None) -> ArqRedis:
    return await create_pool(get_redis_settings(settings))


async def enqueue_embed_job(
    redis_pool: ArqRedis,
    tenant_id: str,
    document_id: str,
    model_id: str,
    model_version: str,
) -> Job | None:
    return await redis_pool.enqueue_job(
        "embed_chunks",
        _queue_name=EMBED_QUEUE_NAME,
        tenant_id=tenant_id,
        document_id=document_id,
        model_id=model_id,
        model_version=model_version,
    )
