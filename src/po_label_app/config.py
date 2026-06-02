from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_PATH = Path("config.yaml")


class AppConfig:
    def __init__(self, data: dict[str, Any], path: Path):
        self.data = data
        self.path = path

    @property
    def portal_url(self) -> str:
        return str(self.data["portal_url"])

    @property
    def selectors(self) -> dict[str, Any]:
        return dict(self.data.get("selectors", {}))

    @property
    def texts(self) -> dict[str, Any]:
        return dict(self.data.get("texts", {}))

    @property
    def timing(self) -> dict[str, Any]:
        return dict(self.data.get("timing", {}))

    @property
    def debug(self) -> dict[str, Any]:
        return dict(self.data.get("debug", {}))

    def printer_target(self, printer_code: str) -> str:
        mapping = self.data.get("printer_mapping", {})
        normalized = (printer_code or "").strip().upper()
        if normalized in {"IN", "VN"}:
            return str(mapping[normalized])
        return str(mapping.get(normalized, mapping.get("default", "Hong Kong [20]")))


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    if not data.get("portal_url"):
        raise ValueError("config.yaml must define portal_url")
    return AppConfig(data=data, path=config_path)
