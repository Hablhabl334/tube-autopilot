#!/usr/bin/env python3
"""gemini_diag.py — run INSIDE GitHub Actions to get full Gemini error detail.

Tests, for each provided key:
  1. ListModels            (region / permission signal)
  2. generateContent       on the model chain (full error bodies printed)
  3. interactions.create   (the new 2026 API surface Google recommends)

Prints everything with clear markers so the log is directly actionable.
"""
import os
import sys

MODELS = ["gemini-flash-latest", "gemini-3.6-flash", "gemini-2.5-flash",
          "gemini-2.0-flash"]

KEYS = {}
for var in ("GEMINI_API_KEY", "GEMINI_KEY_FACTS", "GEMINI_KEY_TECH"):
    v = os.environ.get(var)
    if v:
        KEYS[var] = v

from google import genai  # noqa: E402

for label, key in KEYS.items():
    print(f"\n{'=' * 62}\nKEY {label} (len {len(key)}, prefix {key[:6]}…)\n{'=' * 62}")
    client = genai.Client(api_key=key)

    print("\n--- ListModels ---")
    try:
        names = [m.name.replace("models/", "")
                 for m in client.models.list()
                 if "generateContent" in list(
                     getattr(m, "supported_generation_methods", []) or [])]
        print(f"OK ({len(names)} models): {', '.join(sorted(names)[:15])}")
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {str(e)[:600]}")

    print("\n--- generateContent (full errors) ---")
    for model in MODELS:
        try:
            r = client.models.generate_content(
                model=model, contents="Reply with exactly: OK",
                config={"response_mime_type": "application/json",
                        "temperature": 0.0})
            print(f"  {model:<22} OK -> {(r.text or '')[:80]!r}")
        except Exception as e:
            print(f"  {model:<22} FAIL {type(e).__name__}: {str(e)[:500]}")

    print("\n--- interactions.create (new API surface) ---")
    for model in ("gemini-3.6-flash", "gemini-flash-latest"):
        try:
            r = client.interactions.create(model=model,
                                           input="Reply with exactly: OK")
            out = getattr(r, "output", None)
            print(f"  {model:<22} OK -> {str(out)[:200]}")
        except Exception as e:
            print(f"  {model:<22} FAIL {type(e).__name__}: {str(e)[:500]}")

print("\nDIAG DONE")
