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
    raw_sources = payload.get("sources", [])

    # settings.enabled_source_id_prefixes 가 있으면 해당 prefix 로 시작하는 source 만 로드
    # 비용·시간 절약을 위해 광역시 우선순위 운영 시 사용.
    enabled_prefixes: list[str] = settings.get("enabled_source_id_prefixes") or []
    if enabled_prefixes:
        raw_sources = [
            s for s in raw_sources
            if any(s["id"].startswith(prefix) for prefix in enabled_prefixes)
        ]

    sources = [Source(**item) for item in raw_sources]
    return settings, sources

