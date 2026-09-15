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
    video = cfg.get("mode") == "video"
    key = gemini_key()
    if key:
        for attempt in (1, 2):
            try:
                data = _gemini(cfg, topic, key, strict=(attempt == 2), video=video)
                if _validate(cfg, data, video=video):
                    data["source"] = "gemini"
                    data["topic"] = topic["topic"]
                    return data
                log("   ⚠ Gemini output failed validation, retrying…")
            except Exception as e:
                log(f"   ⚠ Gemini attempt {attempt} failed: {type(e).__name__}: {e}")
    data = _from_bank(cfg, topic, rng, video=video)
    data["source"] = "bank"
    return data


# Model chain — first model that answers wins and is cached for the process.
# "gemini-flash-latest" is Google's auto-updating alias (always the newest
# stable Flash), so the factory keeps working FOREVER even when Google
# retires a specific version (gemini-2.5-flash was retired for new users in
# 2026 — exactly the kind of rotation this chain absorbs silently).
GEMINI_MODELS = [
    "gemini-flash-latest",     # auto-alias -> newest stable Flash
    "gemini-3.6-flash",        # current stable Flash (explicit pin)
    "gemini-2.5-flash",        # legacy pins, kept as dead-man fallbacks
    "gemini-2.0-flash",
]
_working_model: str | None = None


def _generate_json(client, prompt: str) -> dict:
    """generateContent across the model chain; returns parsed JSON.

    Any single model being retired/unavailable just falls through to the
    next name, so no Google-side model rotation can ever break a video.
    """
    global _working_model
    order = ([_working_model] if _working_model else []) + \
            [m for m in GEMINI_MODELS if m != _working_model]
    last_err: Exception | None = None
    for model in order:
        try:
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config={"response_mime_type": "application/json", "temperature": 1.0},
            )
            data = json.loads(resp.text)
            _working_model = model
            return data
        except Exception as e:
            last_err = e
            log(f"   ⚠ Gemini model '{model}' unavailable ({type(e).__name__}) — trying next…")
    raise last_err


def _gemini(cfg: dict, topic: dict, key: str, strict: bool, video: bool = False) -> dict:
    from google import genai

    persona = PERSONAS.get(cfg["niche"], "a viral YouTube Shorts channel")
    context = ""
    if topic.get("headlines"):
        bullets = "\n".join(f"- {h}" for h in topic["headlines"][:4])
        context = f"Live trending context (use as inspiration, do NOT copy verbatim):\n{bullets}\n"
    memory = intelligence.hints_for(cfg)
    memory_block = f"Performance memory (what your audience rewarded last week): {memory}.\n" if memory else ""
    topic_str = topic.get("topic") or "today's theme"

    if video:
        shape = """Write one long-form YouTube video script (about 100-120 seconds,
~240-290 spoken words).

Hard rules:
- hook: max 10 words, stops the scroll instantly
- 12 to 14 scenes, each 15-24 words, simple spoken language (grade 6 reading level)
- build a mini-arc: setup, escalation, payoff
- outro: max 14 words, asks for a follow or save"""
    else:
        shape = """Write one YouTube Shorts script (about 40 seconds, ~95-110 spoken words).

Hard rules:
- hook: max 8 words, stops the scroll instantly
- 5 or 6 scenes, each 12-22 words, simple spoken language (grade 6 reading level)
- outro: max 12 words, asks for a follow or save"""

    prompt = f"""You are the head writer for "{cfg['display_name']}', {persona}.
{shape}

Topic: {topic_str}
{context}{memory_block}
- no hashtags or emojis inside hook/scenes/outro
- title: max 60 characters, specific and curiosity-driven, never clickbait lies
- tags: 10-15 short lowercase tags
- only state well-established, verifiable facts — never invent statistics or events
{"- be extra careful to follow the JSON schema EXACTLY" if strict else ""}

Return ONLY valid JSON matching this schema:
{SCHEMA_HINT}"""

    client = genai.Client(api_key=key)
    return _generate_json(client, prompt)


def _validate(cfg: dict, data: dict, video: bool = False) -> bool:
    try:
        scenes = [clean_text(s) for s in data["scenes"] if clean_text(s)]
        words = sum(len(s.split()) for s in scenes)
        if video:
            if not (9 <= len(scenes) <= 18):
                return False
            if not (150 <= words <= 400):
                return False
        else:
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


def _longform_from_bank(cfg: dict, topic: dict, rng: random.Random) -> dict:
    """Stitch several bank entries into one ~100s long-form script.

    Reuses the existing single-Short banks as building blocks, so the
    long-form video also works fully offline (no Gemini key required).
    """
    niche = cfg["niche"]
    hint = intelligence.style_hint(cfg["id"])

    if niche == "facts":
        picks = rng.sample(bank.FACTS, 10)
        scenes = [f"Fact {i}: {p}" for i, p in enumerate(picks, 1)]
        title = bank._biased(rng, [
            "10 Facts That Sound Fake (All True)",
            "10 True Facts Nobody Believes At First",
            "10 Facts That Break Your Brain Slowly",
        ], hint)
        thumb = "10 REAL FACTS"
    elif niche == "money":
        rules = rng.sample(bank.MONEY_RULES, 8)
        scenes = [f"Rule {i}: {r}" for i, r in enumerate(rules, 1)]
        title = bank._biased(rng, [
            "8 Money Rules That Quietly Build Wealth",
            "8 Money Rules Schools Skip Completely",
            "The 8 Money Rules I'd Teach My Younger Self",
        ], hint)
        thumb = "8 MONEY RULES"
    elif niche == "tech":
        scenes = []
        for h in (topic.get("headlines") or [])[:4]:
            h = h.strip().rstrip(".")
            if h:
                scenes.append(f"In AI news today: {h}.")
        while len(scenes) < 10:
            scenes.append(f"Quick fact: {rng.choice(bank.TECH_FALLBACK_FACTS)}")
        scenes = scenes[:11]
        title = bank._biased(rng, [
            "The AI News You Missed Today",
            "Today In AI: Everything That Matters",
        ], hint)
        thumb = "AI NEWS DROP"
    else:  # motivation
        quotes = rng.sample(bank.QUOTES, 4)
        scenes = []
        for q, a in quotes:
            scenes.append(q)
            scenes.append(f"{a} said that for a reason.")
            scenes.append(rng.choice(bank.MOTIVATION_LESSONS))
        title = bank._biased(rng, [
            "4 Quotes That Will Rewrite Your Standards",
            "4 Quotes Worth Hearing Every Single Week",
            "The 4 Quotes That Change How You Work",
        ], hint)
        thumb = "4 POWER QUOTES"

    hooks = {"motivation": bank.MOTIVATION_HOOKS, "facts": bank.FACTS_HOOKS,
             "tech": bank.TECH_HOOKS, "money": bank.MONEY_HOOKS}
    outros = {"motivation": bank.MOTIVATION_OUTROS, "facts": bank.FACTS_OUTROS,
              "tech": bank.TECH_OUTROS, "money": bank.MONEY_OUTROS}
    return {
        "hook": rng.choice(hooks.get(niche, bank.FACTS_HOOKS)),
        "scenes": scenes,
        "outro": rng.choice(outros.get(niche, bank.FACTS_OUTROS)),
        "title": title,
        "thumbnail_text": thumb,
        "topic": f"long-form {niche} compilation",
    }


def _from_bank(cfg: dict, topic: dict, rng: random.Random, video: bool = False) -> dict:
    if video:
        data = _longform_from_bank(cfg, topic, rng)
    else:
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
