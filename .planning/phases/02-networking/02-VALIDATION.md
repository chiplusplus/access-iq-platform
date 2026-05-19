---
phase: 02
slug: networking
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-19
---

# Phase 02 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x with aws-cdk-lib assertions |
| **Config file** | `pyproject.toml` (root workspace) |
| **Quick run command** | `pytest tests/unit/test_network_stack.py -x` |
| **Full suite command** | `make test` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/unit/test_network_stack.py -x`
- **Per wave merge:** `make test`
- **Phase gate:** `make ci` (ruff format + lint + mypy + full test suite green)

---

## Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REQ-NET-01 | VPC exists with 10.10.0.0/16 CIDR | unit | `pytest tests/unit/test_network_stack.py::test_vpc_cidr -x` | Wave 0 |
| REQ-NET-01 | 4 subnets (2 public + 2 private) across 2 AZs | unit | `pytest tests/unit/test_network_stack.py::test_two_private_two_public_subnets -x` | Wave 0 |
| REQ-NET-01 | Single NAT gateway in dev | unit | `pytest tests/unit/test_network_stack.py::test_single_nat_gateway -x` | Wave 0 |
| REQ-NET-02 | CfnVPCPeeringConnection resource exists | unit | `pytest tests/unit/test_network_stack.py::test_vpc_peering_resource -x` | Wave 0 |
| REQ-NET-02 | Platform-side CfnRoute to Trust CIDR exists | unit | `pytest tests/unit/test_network_stack.py::test_platform_peering_routes -x` | Wave 0 |
| REQ-NET-02 | AwsCustomResource for Trust routes exists | unit | `pytest tests/unit/test_network_stack.py::test_trust_route_custom_resource -x` | Wave 0 |
| REQ-NET-02 | ECS SG has no 0.0.0.0/0 egress (deny-by-default) | unit | `pytest tests/unit/test_network_stack.py::test_ecs_sg_deny_all_outbound -x` | Wave 0 |
| REQ-NET-03 | S3 gateway endpoint present | unit | `pytest tests/unit/test_network_stack.py::test_s3_gateway_endpoint -x` | Wave 0 |
| REQ-NET-03 | 5 interface endpoints present | unit | `pytest tests/unit/test_network_stack.py::test_interface_endpoints_count -x` | Wave 0 |
| REQ-NET-03 | Full suite synths cleanly (dev + prod) | unit | `pytest tests/unit/test_app_synth.py -x` | Extend existing |

---

## Wave 0 Gaps

- [ ] `tests/unit/test_network_stack.py` — covers all REQ-NET-* assertions above
- [ ] `tests/unit/test_app_synth.py` — extend existing to include NetworkStack synth with context params
