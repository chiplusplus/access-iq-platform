from aws_cdk import Tags
from constructs import IConstruct

REQUIRED_TAGS = [
    "Environment",
    "Project",
    "ManagedBy",
    "CostCenter",
]


def apply_tags(scope: IConstruct, tags: dict) -> None:
    missing = [t for t in REQUIRED_TAGS if t not in tags]
    if missing:
        raise ValueError(f"Missing required tags in config: {missing}")

    for k, v in tags.items():
        Tags.of(scope).add(k, v)
