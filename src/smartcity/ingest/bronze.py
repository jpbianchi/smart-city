"""Bronze landing zone: raw payloads are written append-only, never mutated.

Layout: data/bronze/feed=<name>/date=YYYY-MM-DD/<HHMMSS_microseconds>.json
Each file is an envelope {feed, polled_at, source_url, payload} so lineage
survives even if the upstream feed changes shape.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from smartcity.config import BRONZE_DIR


def write_bronze_file(feed: str, content: bytes, ext: str, source_url: str,
                      meta: dict | None = None) -> Path:
    """Land a raw non-JSON payload (csv, gz...) with a .meta.json sidecar."""
    now = datetime.now(timezone.utc)
    out_dir = BRONZE_DIR / f"feed={feed}" / f"date={now:%Y-%m-%d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{now:%H%M%S_%f}"
    out_path = out_dir / f"{stem}.{ext}"
    out_path.write_bytes(content)
    sidecar = {"feed": feed, "polled_at": now.isoformat(), "source_url": source_url,
               "file": out_path.name, **(meta or {})}
    (out_dir / f"{stem}.meta.json").write_text(json.dumps(sidecar))
    return out_path


def write_bronze(feed: str, payload, source_url: str) -> Path:
    now = datetime.now(timezone.utc)
    envelope = {
        "feed": feed,
        "polled_at": now.isoformat(),
        "source_url": source_url,
        "payload": payload,
    }
    out_dir = BRONZE_DIR / f"feed={feed}" / f"date={now:%Y-%m-%d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{now:%H%M%S_%f}.json"
    with open(out_path, "w") as f:
        json.dump(envelope, f)
    return out_path
