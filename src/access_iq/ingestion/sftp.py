from __future__ import annotations

import hashlib
import io
import stat
import uuid
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

import boto3
import paramiko
import structlog

from access_iq.ingestion.idempotency import should_skip_if_already_successful
from access_iq.ingestion.manifests import (
    Manifest,
    ManifestStatus,
    build_manifest_prefix,
    s3_kms_args,
    utc_now_iso,
    write_manifest,
)

log = structlog.get_logger(__name__)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@dataclass
class FileResult:
    filename: str
    remote_path: str
    bytes: int
    sha256: str
    s3_key: str
    status: str
    error: str | None = None


def ingest_sftp_directory_to_bronze(
    *,
    source_name: str,
    host: str,
    port: int,
    username: str,
    password: str | None = None,
    private_key: str | None = None,
    remote_dir: str,
    platform_bucket: str,
    ingest_date: date,
    env: str,
    aws_region: str,
    aws_profile_platform: str | None = None,
    fail_fast: bool = True,
    kms_key_arn: str | None = None,
) -> dict[str, Any]:
    run_id = str(uuid.uuid4())
    started_at = utc_now_iso()

    bound_log = log.bind(run_id=run_id, source=source_name, env=env)

    session = boto3.Session(profile_name=aws_profile_platform, region_name=aws_region)
    s3 = session.client("s3")
    manifest_prefix = build_manifest_prefix(source=source_name, ingest_date=ingest_date.isoformat())

    if should_skip_if_already_successful(
        s3=s3, bucket=platform_bucket, manifest_prefix=manifest_prefix
    ):
        bound_log.info("ingest_skipped", reason="latest_manifest_success")
        return {
            "source": source_name,
            "run_id": run_id,
            "env": env,
            "ingest_date": ingest_date.isoformat(),
            "status": "skipped",
            "reason": "latest_manifest_success",
        }

    results: list[FileResult] = []
    status: ManifestStatus = "success"
    run_errors: list[str] = []

    if not password and not private_key:
        raise ValueError("Either password or private_key must be provided")

    transport = paramiko.Transport((host, port))
    try:
        if private_key:
            pkey = paramiko.RSAKey.from_private_key(io.StringIO(private_key))
            transport.connect(username=username, pkey=pkey)
        else:
            transport.connect(username=username, password=password)
        sftp = paramiko.SFTPClient.from_transport(transport)

        if sftp is None:
            raise RuntimeError("Failed to create SFTP client")

        names = sorted(sftp.listdir(remote_dir))

        for fname in names:
            remote_path = f"{remote_dir.rstrip('/')}/{fname}"
            try:
                attr = sftp.stat(remote_path)
                if attr.st_mode is not None and stat.S_ISDIR(attr.st_mode):
                    continue

                with sftp.open(remote_path, "rb") as f:
                    data = f.read()

                digest = sha256_bytes(data)
                s3_key = (
                    f"bronze/source={source_name}/entity=appointments/"
                    f"ingest_date={ingest_date.isoformat()}/run_id={run_id}/files/{fname}"
                )

                extra = s3_kms_args(kms_key_arn)
                s3.upload_fileobj(
                    Fileobj=io.BytesIO(data),
                    Bucket=platform_bucket,
                    Key=s3_key,
                    ExtraArgs=extra if extra else None,
                )

                results.append(
                    FileResult(
                        filename=fname,
                        remote_path=remote_path,
                        bytes=len(data),
                        sha256=digest,
                        s3_key=s3_key,
                        status="success",
                    )
                )
                bound_log.info("file_uploaded", filename=fname, s3_key=s3_key)
            except Exception as e:
                status = "failed"
                err = f"{type(e).__name__}: {e}"
                run_errors.append(err)
                results.append(
                    FileResult(
                        filename=fname,
                        remote_path=remote_path,
                        bytes=0,
                        sha256="",
                        s3_key="",
                        status="failed",
                        error=err,
                    )
                )
                bound_log.error("file_upload_failed", filename=fname, error=err)
                if fail_fast:
                    break

        sftp.close()

    finally:
        transport.close()

    finished_at = utc_now_iso()

    manifest = Manifest(
        source=source_name,
        env=env,
        run_id=run_id,
        ingest_date=ingest_date.isoformat(),
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        error=run_errors,
        inputs={"host": host, "port": port, "remote_dir": remote_dir},
        outputs={
            "files": [asdict(r) for r in results],
            "files_succeeded": sum(1 for r in results if r.status == "success"),
            "files_failed": sum(1 for r in results if r.status == "failed"),
        },
    )

    write_manifest(s3=s3, bucket=platform_bucket, manifest=manifest, kms_key_arn=kms_key_arn)
    bound_log.info("ingest_done", status=status)
    return manifest.model_dump()
