from arq import ArqRedis, create_pool
from arq.connections import RedisSettings
from arq.jobs import Job
from pydantic_settings import BaseSettings, SettingsConfigDict


class QueueSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    redis_host: str = "localhost"
    redis_port: int = 6379


def get_redis_settings(settings: QueueSettings | None = None) -> RedisSettings:
    settings = settings or QueueSettings()
    return RedisSettings(host=settings.redis_host, port=settings.redis_port)


async def get_redis_pool(settings: QueueSettings | None = None) -> ArqRedis:
    return await create_pool(get_redis_settings(settings))


async def enqueue_parse_job(
    redis_pool: ArqRedis,
    tenant_id: str,
    document_id: str,
    bucket: str,
    key: str,
    mime_type: str,
) -> Job | None:
    return await redis_pool.enqueue_job(
        "parse_document",
        tenant_id=tenant_id,
        document_id=document_id,
        bucket=bucket,
        key=key,
        mime_type=mime_type,
    )
