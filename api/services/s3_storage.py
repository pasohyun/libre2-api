from __future__ import annotations

import mimetypes
from pathlib import Path
from urllib.parse import quote

import boto3

import config


def is_s3_enabled() -> bool:
    if not config.ENABLE_S3_UPLOAD:
        return False
    return bool(config.S3_BUCKET)


def _build_public_url(object_key: str) -> str:
    if config.S3_PUBLIC_BASE_URL:
        base = config.S3_PUBLIC_BASE_URL.rstrip("/")
        return f"{base}/{quote(object_key)}"

    bucket = config.S3_BUCKET
    region = config.AWS_REGION
    encoded_key = quote(object_key)
    if region == "us-east-1":
        return f"https://{bucket}.s3.amazonaws.com/{encoded_key}"
    return f"https://{bucket}.s3.{region}.amazonaws.com/{encoded_key}"


def _s3_client():
    client_kwargs = {"region_name": config.AWS_REGION}
    if config.AWS_ACCESS_KEY_ID and config.AWS_SECRET_ACCESS_KEY:
        client_kwargs["aws_access_key_id"] = config.AWS_ACCESS_KEY_ID
        client_kwargs["aws_secret_access_key"] = config.AWS_SECRET_ACCESS_KEY
    if config.S3_ENDPOINT_URL:
        client_kwargs["endpoint_url"] = config.S3_ENDPOINT_URL
    return boto3.client("s3", **client_kwargs)


def upload_bytes(*, content: bytes, object_key: str, content_type: str | None = None) -> str:
    client = _s3_client()
    put_kwargs = {
        "Bucket": config.S3_BUCKET,
        "Key": object_key,
        "Body": content,
    }
    if content_type:
        put_kwargs["ContentType"] = content_type
    client.put_object(**put_kwargs)

    return _build_public_url(object_key)


def upload_file(*, file_path: str, object_key: str | None = None, content_type: str | None = None) -> str:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(file_path)

    key = object_key or path.name
    guessed_type = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    data = path.read_bytes()
    return upload_bytes(content=data, object_key=key, content_type=guessed_type)
