"""S3 object storage service (Story 2.2).

Streaming upload / download used by the document ingestion pipeline. Toggles
between LocalStack (local dev) and real AWS via `settings.use_localstack`,
matching the convention established in `scripts/s3_artifact_store.py`.
"""

import logging
import os

import boto3
from botocore.exceptions import ClientError

from app.core.config import settings

logger = logging.getLogger(__name__)


class S3Storage:
    def __init__(self, bucket_name: str | None = None):
        self.bucket_name = bucket_name or settings.s3_bucket_name
        self.client = self._build_client()

    def _build_client(self):
        """Wires boto3 to LocalStack or real AWS based on settings."""
        kwargs = {"region_name": settings.aws_region}
        if settings.use_localstack:
            # LocalStack accepts dummy credentials; real env vars override these.
            kwargs.update(
                {
                    "endpoint_url": settings.localstack_endpoint,
                    "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID", "test"),
                    "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
                }
            )
        return boto3.client("s3", **kwargs)

    def ensure_bucket_exists(self) -> None:
        """Creates the target bucket only when it does not already exist."""
        try:
            self.client.head_bucket(Bucket=self.bucket_name)
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchBucket"):
                self._provision_bucket()
            else:
                logger.error("Unexpected error checking bucket: %s", exc)
                raise

    def _provision_bucket(self) -> None:
        """Region-aware bucket creation; us-east-1 forbids a LocationConstraint."""
        if settings.aws_region == "us-east-1":
            self.client.create_bucket(Bucket=self.bucket_name)
        else:
            self.client.create_bucket(
                Bucket=self.bucket_name,
                CreateBucketConfiguration={"LocationConstraint": settings.aws_region},
            )
        logger.info("Bucket '%s' provisioned.", self.bucket_name)

    def stream_upload(self, key: str, fileobj, content_type: str | None = None) -> str:
        """Streams a file-like object straight into S3 (no full-buffer in memory).

        `fileobj` must be seekable — FastAPI's UploadFile.file (a
        SpooledTemporaryFile) satisfies this, enabling boto3 multipart uploads.
        """
        self.ensure_bucket_exists()
        extra = {"ContentType": content_type} if content_type else None
        self.client.upload_fileobj(fileobj, self.bucket_name, key, ExtraArgs=extra)
        logger.info("Streamed upload → s3://%s/%s", self.bucket_name, key)
        return key

    def download_to_path(self, key: str, dest_path: str) -> str:
        """Downloads an S3 object to a local path (used by the worker to parse it)."""
        self.client.download_file(self.bucket_name, key, dest_path)
        logger.info("Downloaded s3://%s/%s → %s", self.bucket_name, key, dest_path)
        return dest_path
