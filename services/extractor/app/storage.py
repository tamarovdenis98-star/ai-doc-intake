"""S3 (MinIO) for originals. Objects are addressed by content hash, so writing the same file again is a no-op."""
from __future__ import annotations

import io

from minio import Minio
from minio.error import S3Error

from . import config

_client: Minio | None = None


def client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(config.S3_ENDPOINT, access_key=config.S3_ACCESS_KEY, secret_key=config.S3_SECRET_KEY, secure=config.S3_SECURE)
        if not _client.bucket_exists(config.S3_BUCKET):
            _client.make_bucket(config.S3_BUCKET)
    return _client


def key_for(sha256: str, ext: str) -> str:
    return f"originals/{sha256[:2]}/{sha256}.{ext}"


def put(key: str, data: bytes, mime: str) -> None:
    c = client()
    try:
        c.stat_object(config.S3_BUCKET, key)
        return                                   # already stored: same hash, same bytes
    except S3Error as e:
        if e.code not in ("NoSuchKey", "NoSuchObject", "ResourceNotFound"):
            raise
    c.put_object(config.S3_BUCKET, key, io.BytesIO(data), len(data), content_type=mime)


def get(key: str) -> bytes:
    r = client().get_object(config.S3_BUCKET, key)
    try:
        return r.read()
    finally:
        r.close()
        r.release_conn()
