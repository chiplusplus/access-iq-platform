#!/usr/bin/env python3
"""One-shot Lambda to test TCP connectivity from Platform VPC to Trust RDS.

Deploy:
  cd infra && cdk deploy ConnectivityTestStack \
    -c env=dev \
    -c trust_vpc_id=vpc-xxx \
    -c trust_route_table_ids=rtb-aaa,rtb-bbb

Invoke:
  aws lambda invoke --function-name access-iq-connectivity-test \
    --profile CHI-Engineer-222308823356 --region eu-west-2 \
    /dev/stdout

Tear down:
  cd infra && cdk destroy ConnectivityTestStack \
    -c env=dev \
    -c trust_vpc_id=vpc-xxx \
    -c trust_route_table_ids=rtb-aaa,rtb-bbb
"""

from __future__ import annotations

import json
import socket
import time

TARGETS: list[tuple[str, str, int]] = [
    (
        "Trust RDS (PostgreSQL)",
        "northshiretruststack-trustrds86184de0-wczrrjifiuy2.cbgwacwgo3gt.eu-west-2.rds.amazonaws.com",
        5432,
    ),
]


def handler(event: dict, context: object) -> dict:
    results = []
    for name, host, port in TARGETS:
        start = time.time()
        try:
            sock = socket.create_connection((host, port), timeout=5)
            sock.close()
            latency_ms = round((time.time() - start) * 1000, 1)
            results.append(
                {
                    "name": name,
                    "host": host,
                    "port": port,
                    "status": "PASS",
                    "latency_ms": latency_ms,
                }
            )
        except (TimeoutError, OSError) as e:
            results.append(
                {
                    "name": name,
                    "host": host,
                    "port": port,
                    "status": "FAIL",
                    "error": str(e),
                }
            )

    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = len(results) - passed

    body = {
        "summary": f"{passed} passed, {failed} failed",
        "results": results,
    }
    print(json.dumps(body, indent=2))
    return body
