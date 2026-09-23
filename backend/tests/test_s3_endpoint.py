"""Object-storage provider selection and bucket provisioning.

Nothing covered `s3_storage.py` before this, which mattered because the file
makes two decisions from the same settings — where to point boto3, and what
shape of `create_bucket` call to send — and they have to agree. When they don't,
the symptom is a failed *upload*, which reads as a credentials problem and
isn't one.

No network: constructing a boto3 client performs no I/O, and the provisioning
tests swap in a recorder.
"""

import pytest
from botocore.exceptions import ClientError

from app.core.config import settings
from app.services.s3_storage import S3Storage

R2 = "https://abc123.r2.cloudflarestorage.com"


class FakeS3:
    """Records create_bucket kwargs; head_bucket outcome is scripted."""

    def __init__(self, head_error: ClientError | None = None):
        self.head_error = head_error
        self.created: list[dict] = []
        self.head_calls = 0

    def head_bucket(self, **kwargs):
        self.head_calls += 1
        if self.head_error:
            raise self.head_error
        return {}

    def create_bucket(self, **kwargs):
        self.created.append(kwargs)
        return {}


def missing_bucket() -> ClientError:
    return ClientError({"Error": {"Code": "404"}}, "HeadBucket")


@pytest.fixture
def storage(monkeypatch):
    """An S3Storage whose settings are ours and whose client is a recorder."""

    # "missing" is a sentinel resolved per call, so tests don't share one
    # exception instance; None means head_bucket succeeds (the bucket is there).
    def _make(*, region: str, endpoint: str = "", localstack: bool = False,
              head_error: ClientError | None | str = "missing") -> tuple[S3Storage, FakeS3]:
        if head_error == "missing":
            head_error = missing_bucket()
        monkeypatch.setattr(settings, "use_localstack", localstack)
        monkeypatch.setattr(settings, "s3_endpoint_url", endpoint)
        monkeypatch.setattr(settings, "aws_region", region)
        st = S3Storage(bucket_name="probe")
        fake = FakeS3(head_error)
        st.client = fake
        return st, fake

    return _make


# --- which endpoint boto3 is pointed at -------------------------------------


def test_defaults_to_real_aws(monkeypatch):
    monkeypatch.setattr(settings, "use_localstack", False)
    monkeypatch.setattr(settings, "s3_endpoint_url", "")
    monkeypatch.setattr(settings, "aws_region", "us-east-1")

    client = S3Storage(bucket_name="probe").client
    assert "amazonaws.com" in client.meta.endpoint_url


def test_third_party_endpoint_is_honoured(monkeypatch):
    monkeypatch.setattr(settings, "use_localstack", False)
    monkeypatch.setattr(settings, "s3_endpoint_url", R2)
    monkeypatch.setattr(settings, "aws_region", "auto")

    client = S3Storage(bucket_name="probe").client
    assert client.meta.endpoint_url == R2
    assert client.meta.region_name == "auto"


def test_localstack_wins_over_a_stray_third_party_endpoint(monkeypatch):
    """USE_LOCALSTACK=true must keep dev pointed at LocalStack.

    A leftover S3_ENDPOINT_URL in a developer's .env would otherwise silently
    send local uploads to a real provider — and `.env` outranking committed
    defaults is exactly how this project has been broken before.
    """
    monkeypatch.setattr(settings, "use_localstack", True)
    monkeypatch.setattr(settings, "s3_endpoint_url", R2)
    monkeypatch.setattr(settings, "localstack_endpoint", "http://localhost:4566")

    client = S3Storage(bucket_name="probe").client
    assert client.meta.endpoint_url == "http://localhost:4566"


# --- what shape of create_bucket goes out ----------------------------------


def test_third_party_bucket_creation_omits_location_constraint(storage):
    """The fix: R2 rejects a LocationConstraint, and "auto" is not a location.

    Without this, the first upload to R2 fails inside bucket provisioning.
    """
    st, fake = storage(region="auto", endpoint=R2)

    st.ensure_bucket_exists()

    assert fake.created == [{"Bucket": "probe"}]


def test_real_aws_outside_us_east_1_still_sends_location_constraint(storage):
    """Regression guard: AWS *requires* it everywhere except us-east-1."""
    st, fake = storage(region="eu-west-2")

    st.ensure_bucket_exists()

    assert fake.created == [
        {"Bucket": "probe", "CreateBucketConfiguration": {"LocationConstraint": "eu-west-2"}}
    ]


def test_us_east_1_omits_location_constraint(storage):
    """AWS rejects the constraint in us-east-1 — the original special case."""
    st, fake = storage(region="us-east-1")

    st.ensure_bucket_exists()

    assert fake.created == [{"Bucket": "probe"}]


# --- when provisioning should not happen at all ----------------------------


def test_existing_bucket_is_not_recreated(storage):
    """Pre-creating the bucket is the documented path for a scoped key.

    A key scoped to one bucket has no s3:CreateBucket, so this must stay a
    single head_bucket and nothing more.
    """
    st, fake = storage(region="auto", endpoint=R2, head_error=None)

    st.ensure_bucket_exists()

    assert fake.head_calls == 1
    assert fake.created == []


def test_permission_error_is_raised_not_swallowed(storage):
    """A 403 means the name is taken by someone else (bucket names are global).

    Turning that into a create attempt would replace a clear AccessDenied with
    a confusing failure, so it has to propagate.
    """
    denied = ClientError({"Error": {"Code": "403"}}, "HeadBucket")
    st, fake = storage(region="us-east-1", head_error=denied)

    with pytest.raises(ClientError):
        st.ensure_bucket_exists()

    assert fake.created == []
