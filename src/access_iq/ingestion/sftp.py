from __future__ import annotations

import hashlib
import io
import json
import stat
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from typing import Any

import boto3
import paramiko

from access_iq.ingestion.idempotency import should_skip_if_already_successful


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


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
    password: str,
    remote_dir: str,
    platform_bucket: str,
    ingest_date: date,
    env: str,
    aws_region: str,
    aws_profile_platform: str | None = None,
    fail_fast: bool = True,
) -> dict[str, Any]:
    """
    Ingest all files under remote_dir into Bronze.
    Writes raw files (unchanged) and a single manifest for the run.

    Bronze key structure:
      bronze/source=<source_name>/entity=appointments/ingest_date=.../run_id=.../files/<filename>
    """
    run_id = str(uuid.uuid4())
    started_at = utc_now()

    session = boto3.Session(profile_name=aws_profile_platform, region_name=aws_region)
    s3 = session.client("s3")
    manifest_prefix = f"_manifests/source={source_name}/ingest_date={ingest_date.isoformat()}"

    if should_skip_if_already_successful(
        s3=s3, bucket=platform_bucket, manifest_prefix=manifest_prefix
    ):
        print("Ingest already successful for this date and source. Skipping.")
        return {
            "source": source_name,
            "run_id": run_id,
            "env": env,
            "ingest_date": ingest_date.isoformat(),
            "status": "skipped",
            "reason": "latest_manifest_success",
        }

    results: list[FileResult] = []
    status = "success"
    error: str | None = None

    transport = paramiko.Transport((host, port))
    try:
        transport.connect(username=username, password=password)
        sftp = paramiko.SFTPClient.from_transport(transport)

        if sftp is None:
            raise RuntimeError("Failed to create SFTP client")

        # List files (skip directories)
        names = sftp.listdir(remote_dir)
        names = sorted(names)

        for fname in names:
            remote_path = f"{remote_dir.rstrip('/')}/{fname}"
            try:
                # ensure it's a file
                attr = sftp.stat(remote_path)
                # crude dir check: S_ISDIR bit

                if attr.st_mode is not None and stat.S_ISDIR(attr.st_mode):
                    continue

                with sftp.open(remote_path, "rb") as f:
                    data = f.read()

                digest = sha256_bytes(data)
                s3_key = (
                    f"bronze/source={source_name}/entity=appointments/"
                    f"ingest_date={ingest_date.isoformat()}/run_id={run_id}/files/{fname}"
                )

                s3.upload_fileobj(Fileobj=io.BytesIO(data), Bucket=platform_bucket, Key=s3_key)

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
            except Exception as e:
                status = "failed"
                err = f"{type(e).__name__}: {e}"
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
                if fail_fast:
                    error = err
                    break

        sftp.close()

    finally:
        transport.close()

    finished_at = utc_now()

    manifest = {
        "source": source_name,
        "env": env,
        "run_id": run_id,
        "ingest_date": ingest_date.isoformat(),
        "started_at": started_at,
        "finished_at": finished_at,
        "status": status,
        "error": error,
        "inputs": {
            "host": host,
            "port": port,
            "remote_dir": remote_dir,
        },
        "outputs": {
            "files": [asdict(r) for r in results],
            "files_succeeded": sum(1 for r in results if r.status == "success"),
            "files_failed": sum(1 for r in results if r.status == "failed"),
        },
    }

    manifest_key = f"_manifests/source={source_name}/ingest_date={ingest_date.isoformat()}/run_id={run_id}.json"

    s3.put_object(
        Bucket=platform_bucket,
        Key=manifest_key,
        Body=json.dumps(manifest, indent=2).encode("utf-8"),
        ContentType="application/json",
    )

    return manifest
