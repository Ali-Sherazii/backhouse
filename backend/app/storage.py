import io
from datetime import timedelta
from functools import lru_cache

from minio import Minio

from app.config import get_settings


@lru_cache
def client() -> Minio:
    s = get_settings()
    return Minio(s.minio_endpoint, access_key=s.minio_access_key, secret_key=s.minio_secret_key, secure=s.minio_secure)


def ensure_buckets() -> None:
    s = get_settings()
    for bucket in (s.minio_bucket, s.langfuse_bucket):
        if not client().bucket_exists(bucket):
            client().make_bucket(bucket)


def put_bytes(key: str, data: bytes, content_type: str) -> None:
    client().put_object(get_settings().minio_bucket, key, io.BytesIO(data), len(data), content_type=content_type)


def get_bytes(key: str) -> bytes:
    resp = client().get_object(get_settings().minio_bucket, key)
    try:
        return resp.read()
    finally:
        resp.close()
        resp.release_conn()


def presigned_url(key: str, minutes: int = 30) -> str:
    """Only reachable where MINIO_ENDPOINT resolves; the browser uses the api proxy routes instead."""
    return client().presigned_get_object(get_settings().minio_bucket, key, expires=timedelta(minutes=minutes))


def page_key(document_id: int, page: int) -> str:
    return f"pages/{document_id}/{page}.png"
