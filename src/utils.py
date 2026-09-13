"""Shared utilities: logging, subprocess helpers, text sanitizing."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager

ICONS = {
    "topic": "🔭", "script": "✍️", "tts": "🎙️", "captions": "💬",
    "visuals": "🎨", "music": "🎵", "render": "🎬", "thumb": "🖼️",
    "seo": "🧲", "upload": "🚀", "history": "🗃️", "done": "✅",
}


def log(msg: str) -> None:
    print(msg, flush=True)


@contextmanager
def step(icon: str, label: str):
    """Log a pipeline step with elapsed time. Usage: with step('tts','Voiceover'): ..."""
    t0 = time.time()
    log(f"\n{ICONS.get(icon, '•')}  {label}")
    yield
    log(f"   └─ done in {time.time() - t0:.1f}s")


def is_ci() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def is_dry_run() -> bool:
    return os.environ.get("DRY_RUN") == "1"


def run(cmd: list[str], cwd: str | None = None, timeout: int = 600) -> subprocess.CompletedProcess:
    """Run a command, raising with stderr tail on failure."""
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-1500:]
        raise RuntimeError(f"command failed ({cmd[0]}): {tail}")
    return proc


def ffmpeg(args: list[str], cwd: str | None = None, timeout: int = 900) -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found on PATH")
    run(["ffmpeg", "-y", "-loglevel", "error", *args], cwd=cwd, timeout=timeout)


def ffprobe_duration(path: str) -> float:
    proc = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "csv=p=0", path])
    return float(proc.stdout.strip())


def clean_text(s: str) -> str:
    """Strip characters that break TTS / ASS / XML payloads."""
    s = s.replace("\u00a0", " ")
    s = re.sub(r"[<>{}\\]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def clamp(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def note_freq(name: str) -> float:
    """'A4' -> 440.0 (supports #/b, e.g. C#3, Eb3)."""
    m = re.match(r"^([A-G])([#b]?)(-?\d)$", name.strip())
    if not m:
        raise ValueError(f"bad note: {name}")
    letter, acc, octv = m.group(1), m.group(2), int(m.group(3))
    semis = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[letter]
    if acc == "#":
        semis += 1
    elif acc == "b":
        semis -= 1
    midi = (octv + 1) * 12 + semis
    return 440.0 * 2 ** ((midi - 69) / 12)
