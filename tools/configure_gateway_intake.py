"""Install bounded gateway settings, preserving a private pre-change backup."""

import copy
import shutil
from datetime import UTC, datetime
from pathlib import Path

import yaml


def configured(source: dict) -> dict:
    result = copy.deepcopy(source)
    result.setdefault("agent", {})["max_turns"] = 8
    plugins = result.setdefault("plugins", {})
    enabled = plugins.setdefault("enabled", [])
    if not isinstance(enabled, list):
        raise ValueError("Review non-list plugins.enabled before changing it")
    if "cube-intake" not in enabled:
        enabled.append("cube-intake")
    if "cube-intake" in plugins.get("disabled", []):
        raise ValueError("cube-intake is explicitly disabled; resolve that setting first")
    return result


def main() -> None:
    path = Path("~/.hermes/config.yaml").expanduser()
    result = configured(yaml.safe_load(path.read_text()))
    backup = path.with_name("config.yaml.pre-intake-" + datetime.now(UTC).strftime("%Y%m%d%H%M%S"))
    shutil.copy2(path, backup)
    backup.chmod(0o600)
    temporary = path.with_suffix(".intake.tmp")
    temporary.write_text(yaml.safe_dump(result, sort_keys=False))
    temporary.chmod(0o600)
    temporary.replace(path)
    print(f"Configured cube-intake and 8-turn gateway ceiling. Backup: {backup}")


if __name__ == "__main__":
    main()
