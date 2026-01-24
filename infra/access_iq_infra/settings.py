import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EnvConfig:
    app_name: str
    env_name: str
    account_id: str
    region: str
    tags: dict[str, str]


def load_env_config(env_name: str) -> EnvConfig:
    path = Path(__file__).resolve().parents[1] / "config" / f"{env_name}.json"
    raw: dict[str, Any] = json.loads(path.read_text())

    return EnvConfig(
        app_name=str(raw["app_name"]),
        env_name=str(raw["env_name"]),
        account_id=str(raw["account_id"]),
        region=str(raw["region"]),
        tags=dict(raw.get("tags", {})),
    )
