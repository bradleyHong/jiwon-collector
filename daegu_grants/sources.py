from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    org: str
    adapter: str
    url: str
    search_url: str = ""
    rss_or_api: str = ""
    api_key_env: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    fallback_url: str = ""
    notes: str = ""


def load_config(path: str | Path = "sources.yaml") -> tuple[dict[str, Any], list[Source]]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    settings = payload.get("settings", {})
    sources = [Source(**item) for item in payload.get("sources", [])]
    return settings, sources

