from typing import IO

import boto3
from botocore.config import Config
from pydantic_settings import BaseSettings, SettingsConfigDict


class StorageSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "ragadmin"
    s3_secret_key: str = "ragadminsecret"
    s3_bucket: str = "rag-documents"
    s3_region: str = "us-east-1"


def get_s3_client(settings: StorageSettings | None = None) -> object:
    settings = settings or StorageSettings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        region_name=settings.s3_region,
    )


def ensure_bucket(s3_client: object, bucket: str) -> None:
    try:
        s3_client.create_bucket(Bucket=bucket)  # type: ignore[attr-defined]
    except s3_client.exceptions.BucketAlreadyOwnedByYou:  # type: ignore[attr-defined]
        pass


def upload_fileobj(s3_client: object, bucket: str, key: str, fileobj: IO[bytes]) -> None:
    s3_client.upload_fileobj(fileobj, bucket, key)  # type: ignore[attr-defined]


def download_fileobj(s3_client: object, bucket: str, key: str, fileobj: IO[bytes]) -> None:
    s3_client.download_fileobj(bucket, key, fileobj)  # type: ignore[attr-defined]


def get_object_size(s3_client: object, bucket: str, key: str) -> int:
    response = s3_client.head_object(Bucket=bucket, Key=key)  # type: ignore[attr-defined]
    return int(response["ContentLength"])
