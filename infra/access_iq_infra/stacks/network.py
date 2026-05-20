"""NetworkStack — stateless Platform VPC, peering, routes, endpoints, security groups.

All resources use DESTROY removal policy. Deploy and destroy each working session.
Trust VPC details are ephemeral and must be passed as CDK context params at synth time.

Required CDK context params:
    -c trust_vpc_id=vpc-xxx
    -c trust_route_table_ids=rtb-aaa,rtb-bbb

See docs/architecture/networking.md and .planning/phases/02-networking/ for design decisions.
"""

from __future__ import annotations

from typing import Any

from aws_cdk import Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk.custom_resources import (
    AwsCustomResource,
    AwsCustomResourcePolicy,
    AwsSdkCall,
    PhysicalResourceId,
)
from constructs import Construct

from access_iq_infra.settings import EnvConfig


class NetworkStack(Stack):
    """
    Stateless: Platform VPC, cross-account VPC peering, route tables, DNS resolution,
    security groups, and VPC endpoints (S3 gateway + 5 interface endpoints).

    Exposes for Phase 3 ECS stack:
        self.vpc          — ec2.Vpc
        self.ecs_task_sg  — ec2.SecurityGroup (deny-by-default egress)

    Required CDK context params:
        -c trust_vpc_id=vpc-xxx
        -c trust_route_table_ids=rtb-aaa,rtb-bbb
    """

    vpc: ec2.Vpc
    ecs_task_sg: ec2.SecurityGroup

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cfg: EnvConfig,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── Section 1: Context validation (fail fast at synth time) ──────────
        # Trust stack is ephemeral — VPC IDs change every session; context only per D-06.
        trust_vpc_id: str | None = self.node.try_get_context("trust_vpc_id")
        trust_rtb_ids_raw: str | None = self.node.try_get_context("trust_route_table_ids")
        if trust_vpc_id is None or trust_rtb_ids_raw is None:
            missing = []
            if trust_vpc_id is None:
                missing.append("trust_vpc_id")
            if trust_rtb_ids_raw is None:
                missing.append("trust_route_table_ids")
            raise ValueError(
                f"Trust VPC context required (missing: {', '.join(missing)}). Pass: "
                "-c trust_vpc_id=vpc-xxx "
                "-c trust_route_table_ids=rtb-aaa,rtb-bbb"
            )
        # Strip whitespace to avoid Pitfall 7 (comma-separated with spaces)
        trust_route_table_ids = [x.strip() for x in trust_rtb_ids_raw.split(",")]
        trust_account_id: str = cfg.iam["trust_account_id"]
        peering_accepter_role_arn = (
            f"arn:aws:iam::{trust_account_id}:role/access-iq-peering-accepter"
        )

        # ── Section 2: VPC (REQ-NET-01) ──────────────────────────────────────
        vpc = ec2.Vpc(
            self,
            "PlatformVpc",
            vpc_name=f"{cfg.app_name}-{cfg.env_name}-platform",
            ip_addresses=ec2.IpAddresses.cidr(cfg.vpc["platform_cidr"]),
            max_azs=cfg.vpc["max_azs"],
            nat_gateways=cfg.vpc["nat_gateways"],
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
            ],
        )

        # ── Section 3: VPC Peering (REQ-NET-02, D-01) ────────────────────────
        # peer_role_arn triggers CloudFormation to assume the Trust role and auto-accept
        # the peering connection — no separate AwsCustomResource needed for acceptance.
        peering = ec2.CfnVPCPeeringConnection(
            self,
            "PlatformToTrustPeering",
            vpc_id=vpc.vpc_id,
            peer_vpc_id=trust_vpc_id,
            peer_owner_id=trust_account_id,
            peer_role_arn=peering_accepter_role_arn,
        )

        # ── Section 4: Platform-side routes (REQ-NET-02) ─────────────────────
        # CDK L2 Vpc does not expose peering routes; must use CfnRoute L1.
        # add_dependency ensures routes are only created after peering reaches ACTIVE.
        for i, subnet in enumerate(vpc.private_subnets):
            route = ec2.CfnRoute(
                self,
                f"TrustRoute{i}",
                route_table_id=subnet.route_table.route_table_id,
                destination_cidr_block=cfg.vpc["trust_cidr"],
                vpc_peering_connection_id=peering.ref,
            )
            route.add_dependency(peering)

        # ── Section 5: Trust-side route update via AwsCustomResource (REQ-NET-02, D-01) ──
        # One AwsCustomResource per Trust route table.
        # on_delete cleans up on cdk destroy — avoids Pitfall 3 (orphaned routes).
        # install_latest_aws_sdk=False avoids Pitfall 2 (Lambda internet access at cold start).
        # from_statements with sts:AssumeRole avoids cross-account policy over-grant (T-02-04).
        trust_route_policy = AwsCustomResourcePolicy.from_statements(
            [
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=["sts:AssumeRole"],
                    resources=[peering_accepter_role_arn],
                )
            ]
        )
        for i, rtb_id in enumerate(trust_route_table_ids):
            trust_cr = AwsCustomResource(
                self,
                f"TrustRouteUpdate{i}",
                on_create=AwsSdkCall(
                    assumed_role_arn=peering_accepter_role_arn,
                    service="EC2",
                    action="createRoute",
                    parameters={
                        "RouteTableId": rtb_id,
                        "DestinationCidrBlock": cfg.vpc["platform_cidr"],
                        "VpcPeeringConnectionId": peering.ref,
                    },
                    physical_resource_id=PhysicalResourceId.of(f"trust-route-{rtb_id}"),
                ),
                on_delete=AwsSdkCall(
                    assumed_role_arn=peering_accepter_role_arn,
                    service="EC2",
                    action="deleteRoute",
                    parameters={
                        "RouteTableId": rtb_id,
                        "DestinationCidrBlock": cfg.vpc["platform_cidr"],
                    },
                    physical_resource_id=PhysicalResourceId.of(f"trust-route-{rtb_id}"),
                ),
                policy=trust_route_policy,
                install_latest_aws_sdk=False,
            )
            trust_cr.node.add_dependency(peering)

        # ── Section 6: DNS resolution via AwsCustomResource (REQ-NET-02, D-03) ──
        # Two calls: requester side (Platform account) and accepter side (Trust account).
        # Both must depend on peering reaching ACTIVE state.

        # Requester side — same account, from_sdk_calls is fine (no cross-account STS).
        dns_requester_cr = AwsCustomResource(
            self,
            "PeeringDnsRequester",
            on_create=AwsSdkCall(
                service="EC2",
                action="modifyVpcPeeringConnectionOptions",
                parameters={
                    "VpcPeeringConnectionId": peering.ref,
                    "RequesterPeeringConnectionOptions": {
                        "AllowDnsResolutionFromRemoteVpc": True,
                    },
                },
                physical_resource_id=PhysicalResourceId.of("peering-dns-requester"),
            ),
            policy=AwsCustomResourcePolicy.from_sdk_calls(resources=["*"]),
            install_latest_aws_sdk=False,
        )
        dns_requester_cr.node.add_dependency(peering)

        # Accepter side — cross-account; must use from_statements with sts:AssumeRole (T-02-04).
        dns_accepter_cr = AwsCustomResource(
            self,
            "PeeringDnsAccepter",
            on_create=AwsSdkCall(
                assumed_role_arn=peering_accepter_role_arn,
                service="EC2",
                action="modifyVpcPeeringConnectionOptions",
                parameters={
                    "VpcPeeringConnectionId": peering.ref,
                    "AccepterPeeringConnectionOptions": {
                        "AllowDnsResolutionFromRemoteVpc": True,
                    },
                },
                physical_resource_id=PhysicalResourceId.of("peering-dns-accepter"),
            ),
            policy=AwsCustomResourcePolicy.from_statements(
                [
                    iam.PolicyStatement(
                        effect=iam.Effect.ALLOW,
                        actions=["sts:AssumeRole"],
                        resources=[peering_accepter_role_arn],
                    )
                ]
            ),
            install_latest_aws_sdk=False,
        )
        dns_accepter_cr.node.add_dependency(peering)

        # ── Section 7: Security Groups (REQ-NET-02, T-02-05) ─────────────────
        # ECS task SG — deny-by-default egress; explicit rules only for required ports.
        # allow_all_outbound=False is CRITICAL — CDK default adds 0.0.0.0/0 egress.
        ecs_sg = ec2.SecurityGroup(
            self,
            "EcsTaskSg",
            vpc=vpc,
            security_group_name=f"{cfg.app_name}-{cfg.env_name}-ecs-task",
            description="ECS ingestion tasks - deny-by-default egress",
            allow_all_outbound=False,
        )
        trust_cidr_peer = ec2.Peer.ipv4(cfg.vpc["trust_cidr"])
        ecs_sg.add_egress_rule(trust_cidr_peer, ec2.Port.tcp(5432), "Trust RDS PostgreSQL")
        ecs_sg.add_egress_rule(trust_cidr_peer, ec2.Port.tcp(22), "Trust SFTP")
        # 443 scoped to Platform VPC only — routes to interface endpoints, not internet
        ecs_sg.add_egress_rule(
            ec2.Peer.ipv4(cfg.vpc["platform_cidr"]),
            ec2.Port.tcp(443),
            "VPC interface endpoints",
        )

        # Endpoint SG — allows HTTPS ingress from Platform VPC; no outbound needed.
        endpoint_sg = ec2.SecurityGroup(
            self,
            "EndpointSg",
            vpc=vpc,
            description="VPC interface endpoint security group",
            allow_all_outbound=False,
        )
        endpoint_sg.add_ingress_rule(
            ec2.Peer.ipv4(cfg.vpc["platform_cidr"]),
            ec2.Port.tcp(443),
            "HTTPS from Platform VPC",
        )

        # ── Section 8: VPC Endpoints (REQ-NET-03, D-07) ──────────────────────
        # S3 gateway endpoint — free; routes Bronze writes off NAT gateway.
        vpc.add_gateway_endpoint(
            "S3Endpoint",
            service=ec2.GatewayVpcEndpointAwsService.S3,
            subnets=[ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS)],
        )

        # Interface endpoints — deploy in both AZs (both private subnets) per Claude's Discretion.
        # private_dns_enabled=True overrides public DNS for service hostnames within VPC.
        for eid, svc in [
            ("SecretsManagerEndpoint", ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER),
            ("KmsEndpoint", ec2.InterfaceVpcEndpointAwsService.KMS),
            ("EcrApiEndpoint", ec2.InterfaceVpcEndpointAwsService.ECR),
            ("EcrDkrEndpoint", ec2.InterfaceVpcEndpointAwsService.ECR_DOCKER),
            ("CloudWatchLogsEndpoint", ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS),
        ]:
            ec2.InterfaceVpcEndpoint(
                self,
                eid,
                vpc=vpc,
                service=svc,
                subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
                security_groups=[endpoint_sg],
                private_dns_enabled=True,
            )

        # ── Section 9: Expose for Phase 3 ECS stack ──────────────────────────
        self.vpc = vpc
        self.ecs_task_sg = ecs_sg
