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

    try:
        raw: dict[str, Any] = json.loads(path.read_text())
    except FileNotFoundError as e:
        raise FileNotFoundError(f"Config file not found at {path}") from e
    except OSError as e:
        raise OSError(f"Error reading config file at {path}: {e}") from e
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in config file at {path}: {e}") from e

    try:
        if raw["env_name"] != env_name:
            raise ValueError(
                f"Config file env_name '{raw['env_name']}' does not match requested environment '{env_name}'"
            )

        return EnvConfig(
            app_name=str(raw["app_name"]),
            env_name=str(raw["env_name"]),
            account_id=str(raw["account_id"]),
            region=str(raw["region"]),
            tags=dict(raw.get("tags", {})),
        )
    except KeyError as e:
        raise KeyError(f"Missing required config key {e} in {path}") from e
