"""Voiceover via Edge-TTS (Microsoft neural voices, free, no API key).

Captures word-level timing (WordBoundary events) used later for:
  - word-synced karaoke captions
  - per-scene video durations that match the narration exactly
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import edge_tts

from .utils import clean_text, log


async def _synthesize(text: str, voice: str, rate: str, volume: str, out_mp3: Path):
    comm = edge_tts.Communicate(text, voice, rate=rate, volume=volume, boundary="WordBoundary")
    audio = bytearray()
    words = []
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            # offsets are in 100-nanosecond units
            words.append({
                "word": clean_text(chunk["text"]),
                "offset_ms": chunk["offset"] / 10_000,
                "duration_ms": chunk["duration"] / 10_000,
            })
    if not audio:
        raise RuntimeError("edge-tts returned no audio")
    out_mp3.write_bytes(bytes(audio))
    return words


def synthesize(cfg: dict, script: dict, out_dir: Path) -> tuple[Path, list[dict], str]:
    """Returns (mp3_path, word_timings, full_spoken_text)."""
    parts = [script["hook"], *script["scenes"], script["outro"]]
    parts = [clean_text(p) for p in parts if clean_text(p)]
    full_text = " ".join(parts)

    out_mp3 = out_dir / "voice.mp3"
    words = asyncio.run(_synthesize(
        full_text, cfg["voice"], cfg.get("voice_rate", "+0%"), "+0%", out_mp3,
    ))
    log(f"   voice: {cfg['voice']} | {len(words)} words | {out_mp3.stat().st_size // 1024} KB")
    (out_dir / "words.json").write_text(json.dumps(words, indent=1))
    return out_mp3, words, full_text
