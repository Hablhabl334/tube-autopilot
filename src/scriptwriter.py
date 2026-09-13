"""Script writer — primary: Gemini free tier (structured JSON). Fallback: banks.

The Gemini prompt is per-channel persona + live trend context. Output is
validated hard (scene count, word budgets, title length) so a malformed
generation can never poison the render pipeline.
"""
from __future__ import annotations

import json
import random

from . import content_bank as bank
from . import intelligence
from .config import gemini_key
from .utils import clean_text, log

PERSONAS = {
    "motivation": "a cinematic motivational channel with a deep, authoritative voice",
    "facts": "a fast, playful 'mind-blowing facts' channel",
    "tech": "a credible, sharp AI/tech news channel that respects the audience's time",
    "money": "a calm, trusted personal-finance channel with practical money wisdom",
}

SCHEMA_HINT = """{
  "hook": "spoken opener, max 8 words",
  "scenes": ["5 to 6 spoken lines, each 12-22 words"],
  "outro": "call to action, max 12 words",
  "title": "YouTube title, max 60 chars, curiosity-driven but truthful",
  "description": "2-sentence video description",
  "tags": ["10-15 lowercase YouTube tags"],
  "thumbnail_text": "3-5 UPPERCASE words for the thumbnail"
}"""


def write_script(cfg: dict, topic: dict, rng: random.Random) -> dict:
    key = gemini_key()
    if key:
        for attempt in (1, 2):
            try:
                data = _gemini(cfg, topic, key, strict=(attempt == 2))
                if _validate(cfg, data):
                    data["source"] = "gemini"
                    data["topic"] = topic["topic"]
                    return data
                log("   ⚠ Gemini output failed validation, retrying…")
            except Exception as e:
                log(f"   ⚠ Gemini attempt {attempt} failed: {type(e).__name__}: {e}")
    data = _from_bank(cfg, topic, rng)
    data["source"] = "bank"
    return data


def _gemini(cfg: dict, topic: dict, key: str, strict: bool) -> dict:
    from google import genai

    persona = PERSONAS.get(cfg["niche"], "a viral YouTube Shorts channel")
    context = ""
    if topic.get("headlines"):
        bullets = "\n".join(f"- {h}" for h in topic["headlines"][:4])
        context = f"Live trending context (use as inspiration, do NOT copy verbatim):\n{bullets}\n"
    memory = intelligence.hints_for(cfg)
    memory_block = f"Performance memory (what your audience rewarded last week): {memory}.\n" if memory else ""
    topic_str = topic.get("topic") or "today's theme"

    prompt = f"""You are the head writer for "{cfg['display_name']}', {persona}.
Write one YouTube Shorts script (about 40 seconds, ~95-110 spoken words).

Topic: {topic_str}
{context}{memory_block}
Hard rules:
- hook: max 8 words, stops the scroll instantly
- 5 or 6 scenes, each 12-22 words, simple spoken language (grade 6 reading level)
- outro: max 12 words, asks for a follow or save
- no hashtags or emojis inside hook/scenes/outro
- title: max 60 characters, specific and curiosity-driven, never clickbait lies
- tags: 10-15 short lowercase tags
- only state well-established, verifiable facts — never invent statistics or events
{"- be extra careful to follow the JSON schema EXACTLY" if strict else ""}

Return ONLY valid JSON matching this schema:
{SCHEMA_HINT}"""

    client = genai.Client(api_key=key)
    resp = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config={"response_mime_type": "application/json", "temperature": 1.0},
    )
    return json.loads(resp.text)


def _validate(cfg: dict, data: dict) -> bool:
    try:
        scenes = [clean_text(s) for s in data["scenes"] if clean_text(s)]
        words = sum(len(s.split()) for s in scenes)
        if not (3 <= len(scenes) <= 8):
            return False
        if not (45 <= words <= 160):
            return False
        if not (5 <= len(data["title"]) <= 90):
            return False
        if not data.get("hook") or not data.get("outro"):
            return False
        tags = data.get("tags") or []
        if not (5 <= len(tags) <= 25):
            return False
        data["scenes"] = scenes
        data["hook"] = clean_text(data["hook"])
        data["outro"] = clean_text(data["outro"])
        data["title"] = clean_text(data["title"])[:90]
        data["description"] = clean_text(data.get("description", ""))
        data["thumbnail_text"] = clean_text(data.get("thumbnail_text", ""))[:30].upper()
        data["tags"] = [clean_text(str(t)).lower().lstrip("#") for t in tags][:20]
        return True
    except Exception:
        return False


def _from_bank(cfg: dict, topic: dict, rng: random.Random) -> dict:
    niche = cfg["niche"]
    hint = intelligence.style_hint(cfg["id"])
    if niche == "motivation":
        data = bank.motivation_bank(rng, style_hint=hint)
    elif niche == "facts":
        data = bank.facts_bank(rng, topic.get("topic"), style_hint=hint)
    elif niche == "tech":
        data = bank.tech_bank(rng, topic.get("headlines", []), style_hint=hint)
    elif niche == "money":
        data = bank.money_bank(rng, style_hint=hint)
    else:
        data = bank.facts_bank(rng, topic.get("topic"), style_hint=hint)
    data.setdefault("description", cfg.get("description_cta", ""))
    data.setdefault("tags", [h.lstrip("#") for h in cfg["hashtags"]][:10])
    data["thumbnail_text"] = data.get("thumbnail_text", "MUST WATCH")[:30]
    return data
