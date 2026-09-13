"""Topic memory — data/history/<channel>.json, committed back by the workflow.

Prevents the system from repeating topics and gives you a permanent,
human-readable log of everything ever published.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path

from .config import HISTORY_DIR


def _path(channel_id: str) -> Path:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    return HISTORY_DIR / f"{channel_id}.json"


def _load(channel_id: str) -> list:
    p = _path(channel_id)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text())
    except Exception:
        return []


def _norm(s: str) -> str:
    return " ".join(s.lower().split())[:60]


def recent_topics(channel_id: str, n: int = 120) -> set[str]:
    return {_norm(e.get("topic", "")) for e in _load(channel_id)[-n:]}


def seen(channel_id: str, topic: str) -> bool:
    return _norm(topic) in recent_topics(channel_id)


def published_today(channel_id: str) -> str | None:
    """Video id already uploaded by this channel today (duplicate-upload guard)."""
    today = datetime.date.today().isoformat()
    for e in reversed(_load(channel_id)):
        if e.get("date") == today and e.get("video_id"):
            return e["video_id"]
    return None


def count_today(channel_id: str) -> int:
    """How many videos this channel already shipped today (multi-upload support)."""
    today = datetime.date.today().isoformat()
    return sum(1 for e in _load(channel_id)
               if e.get("date") == today and e.get("video_id"))


def record(channel_id: str, topic: str, title: str, video_id: str | None,
           slot: int | None = None) -> None:
    entries = _load(channel_id)
    entries.append({
        "date": datetime.date.today().isoformat(),
        "slot": slot,
        "topic": topic[:200],
        "title": title[:200],
        "video_id": video_id,
    })
    entries = entries[-500:]  # keep the file bounded
    _path(channel_id).write_text(json.dumps(entries, indent=1, ensure_ascii=False))
