import os
import json
import logging
import boto3
from botocore.exceptions import ClientError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# Toggle LocalStack vs real AWS via environment
USE_LOCALSTACK = os.getenv("USE_LOCALSTACK", "true").lower() == "true"
LOCALSTACK_ENDPOINT = os.getenv("LOCALSTACK_ENDPOINT", "http://localhost:4566")
BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "proposal-artifacts-local")
AWS_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")


class S3ArtifactStore:
    def __init__(self, bucket_name: str):
        self.bucket_name = bucket_name
        self.client = self._build_client()

    def _build_client(self):
        """Wires boto3 to LocalStack or real AWS based on USE_LOCALSTACK."""
        kwargs = {"region_name": AWS_REGION}

        if USE_LOCALSTACK:
            # LocalStack accepts any dummy credentials; real env vars override these
            kwargs.update({
                "endpoint_url": LOCALSTACK_ENDPOINT,
                "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID", "test"),
                "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
            })

        return boto3.client("s3", **kwargs)

    def ensure_bucket_exists(self) -> None:
        """Creates the target bucket only when it does not already exist."""
        try:
            self.client.head_bucket(Bucket=self.bucket_name)
            logger.info("Bucket '%s' already exists — skipping creation.", self.bucket_name)
        except ClientError as exc:
            # 404 means the bucket is absent; any other code is a real access error
            if exc.response["Error"]["Code"] == "404":
                self._provision_bucket()
            else:
                logger.error("Unexpected error checking bucket: %s", exc)
                raise

    def _provision_bucket(self) -> None:
        """Handles region-aware bucket creation; us-east-1 forbids a LocationConstraint."""
        try:
            if AWS_REGION == "us-east-1":
                self.client.create_bucket(Bucket=self.bucket_name)
            else:
                self.client.create_bucket(
                    Bucket=self.bucket_name,
                    CreateBucketConfiguration={"LocationConstraint": AWS_REGION},
                )
            logger.info("Bucket '%s' provisioned successfully.", self.bucket_name)
        except ClientError as exc:
            logger.error("Bucket creation failed: %s", exc)
            raise

    def upload_artifact(self, s3_key: str, payload: dict) -> str:
        """Serializes payload as JSON and writes it to the resolved S3 object key."""
        try:
            self.client.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=json.dumps(payload, indent=2),
                ContentType="application/json",
            )
            logger.info("Artifact uploaded → s3://%s/%s", self.bucket_name, s3_key)
            return s3_key
        except ClientError as exc:
            logger.error("Upload failed for key '%s': %s", s3_key, exc)
            raise

    def read_artifact(self, s3_key: str) -> dict:
        """Fetches and deserializes a JSON artifact from S3 by object key."""
        try:
            response = self.client.get_object(Bucket=self.bucket_name, Key=s3_key)
            raw_body = response["Body"].read().decode("utf-8")
            return json.loads(raw_body)
        except ClientError as exc:
            logger.error("Read failed for key '%s': %s", s3_key, exc)
            raise


def _build_sample_rfp_artifact() -> dict:
    """Constructs a mock RFP metadata payload mimicking upstream document ingestion."""
    return {
        "document_id": "rfp-2024-dod-001",
        "workspace_id": "a3f7e1c2-9b4d-4e8f-b6a0-12c3d4e5f678",
        "file_name": "dod_military_rfp.pdf",
        "uploaded_at": "2024-06-01T10:00:00Z",
        "processing_status": "pending",
        "metadata": {
            "agency": "Department of Defense",
            "solicitation_number": "W911NF-24-R-0001",
            "estimated_value_usd": 5_000_000,
            "submission_deadline": "2024-07-15",
        },
    }


def main() -> None:
    target = "LocalStack" if USE_LOCALSTACK else "AWS"
    logger.info("Running against: %s | bucket: %s | region: %s", target, BUCKET_NAME, AWS_REGION)

    store = S3ArtifactStore(bucket_name=BUCKET_NAME)

    store.ensure_bucket_exists()

    artifact = _build_sample_rfp_artifact()
    s3_key = f"uploads/{artifact['workspace_id']}/rfp_metadata.json"
    store.upload_artifact(s3_key, artifact)

    retrieved = store.read_artifact(s3_key)
    print("\n--- Retrieved Artifact ---")
    print(json.dumps(retrieved, indent=2))
    print("--------------------------\n")


if __name__ == "__main__":
    main()
