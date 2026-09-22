"""S3 object storage service (Story 2.2).

Streaming upload / download used by the document ingestion pipeline. Toggles
between LocalStack (local dev) and real AWS via `settings.use_localstack`.
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

    @staticmethod
    def _third_party_endpoint() -> str:
        """The non-AWS S3 endpoint in effect, or "" when talking to real AWS.

        LocalStack is deliberately excluded even though it is also an endpoint
        override: it gets its own branch below because it needs dummy
        credentials, which a real provider rejects.

        Both `_build_client` and `_provision_bucket` read this rather than
        testing `settings.s3_endpoint_url` themselves, so the endpoint the
        client points at and the shape of the bucket-creation call cannot
        disagree — which is the failure this whole file keeps running into.
        """
        if settings.use_localstack:
            return ""
        return settings.s3_endpoint_url

    def _build_client(self):
        """Wires boto3 to LocalStack, a third-party S3 provider, or real AWS."""
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
        elif endpoint := self._third_party_endpoint():
            # Cloudflare R2, Backblaze B2, self-hosted MinIO. Credentials still
            # come from the standard AWS_* env vars, which boto3 resolves on its
            # own — only the endpoint differs.
            kwargs["endpoint_url"] = endpoint
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
        # A third-party provider has no AWS regions to constrain a bucket to, and
        # R2 rejects the LocationConstraint outright: it wants
        # AWS_DEFAULT_REGION="auto", which is not a location it will then accept
        # as one. So it takes the same bare call us-east-1 does — otherwise the
        # first upload fails on bucket creation rather than on anything to do
        # with the upload, which reads as a credentials problem and isn't one.
        if settings.aws_region == "us-east-1" or self._third_party_endpoint():
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

    def download_bytes(self, key: str) -> bytes:
        """Reads an S3 object fully into memory (used to stream export artifacts)."""
        obj = self.client.get_object(Bucket=self.bucket_name, Key=key)
        return obj["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket_name, Key=key)
