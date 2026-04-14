"""Object storage abstraction: DO Spaces (S3-compatible) + local fallback.

Usage:
    from strecker import storage
    key = storage.put_file("/tmp/upload.zip", f"uploads/{job_id}/upload.zip")
    storage.get_file(key, "/tmp/worker/upload.zip")
    url = storage.presigned_url(key)  # time-limited download link

Backend selection:
    - If settings.SPACES_BUCKET is set -> Spaces (boto3/S3).
    - Otherwise -> local filesystem rooted at settings.UPLOAD_DIR.
      Keys are treated as relative paths. Dev/testing only.

The web container and worker Droplet both use this module so they share a
single notion of "where the file is." The only config they need in common
is SPACES_BUCKET + credentials (env vars).
"""

import logging
import os
import shutil
from pathlib import Path
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)

_s3_client = None


def _use_spaces() -> bool:
    return bool(settings.SPACES_BUCKET)


def _client():
    """Lazy boto3 client. Raises if boto3 isn't installed."""
    global _s3_client
    if _s3_client is not None:
        return _s3_client
    try:
        import boto3
        from botocore.config import Config
    except ImportError as e:
        raise RuntimeError(
            "boto3 not installed. Add `boto3` to requirements.txt."
        ) from e

    _s3_client = boto3.client(
        "s3",
        region_name=settings.SPACES_REGION,
        endpoint_url=settings.SPACES_ENDPOINT,
        aws_access_key_id=settings.SPACES_KEY,
        aws_secret_access_key=settings.SPACES_SECRET,
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )
    return _s3_client


def put_file(local_path: str, key: str, content_type: Optional[str] = None) -> str:
    """Upload a local file. Returns the storage key."""
    if _use_spaces():
        extra = {"ContentType": content_type} if content_type else {}
        _client().upload_file(
            Filename=local_path,
            Bucket=settings.SPACES_BUCKET,
            Key=key,
            ExtraArgs=extra,
        )
        logger.info("Uploaded to Spaces: %s (%d bytes)",
                    key, os.path.getsize(local_path))
        return key

    # Local fallback
    dest = Path(settings.UPLOAD_DIR) / key
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(local_path, dest)
    return key


def get_file(key: str, local_path: str) -> str:
    """Download a storage key to a local path. Returns local_path."""
    Path(local_path).parent.mkdir(parents=True, exist_ok=True)

    if _use_spaces():
        _client().download_file(
            Bucket=settings.SPACES_BUCKET,
            Key=key,
            Filename=local_path,
        )
        logger.info("Downloaded from Spaces: %s -> %s", key, local_path)
        return local_path

    src = Path(settings.UPLOAD_DIR) / key
    if not src.exists():
        raise FileNotFoundError(f"Storage key not found: {key}")
    shutil.copyfile(src, local_path)
    return local_path


def delete_file(key: str) -> None:
    """Best-effort delete. Swallows errors and logs."""
    try:
        if _use_spaces():
            _client().delete_object(Bucket=settings.SPACES_BUCKET, Key=key)
        else:
            p = Path(settings.UPLOAD_DIR) / key
            p.unlink(missing_ok=True)
    except Exception:
        logger.exception("Failed to delete storage key %s", key)


def presigned_url(key: str, expires_in: Optional[int] = None) -> str:
    """Return a time-limited GET URL. Falls back to a local route for dev."""
    if _use_spaces():
        return _client().generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.SPACES_BUCKET, "Key": key},
            ExpiresIn=expires_in or settings.SPACES_PRESIGN_TTL,
        )
    # Local fallback: caller should proxy through a Flask route.
    # Return a pseudo-path; the download route handles the real fetch.
    return f"local://{key}"


def exists(key: str) -> bool:
    if _use_spaces():
        try:
            _client().head_object(Bucket=settings.SPACES_BUCKET, Key=key)
            return True
        except Exception:
            return False
    return (Path(settings.UPLOAD_DIR) / key).exists()


# --- Key helpers (single source of truth for S3 layout) ---

def upload_zip_key(job_id: str) -> str:
    """Object key for the user's uploaded ZIP."""
    return f"uploads/{job_id}/upload.zip"


def report_key(job_id: str) -> str:
    return f"uploads/{job_id}/output/game_inventory_report.pdf"


def appendix_key(job_id: str) -> str:
    return f"uploads/{job_id}/output/events_appendix.csv"
