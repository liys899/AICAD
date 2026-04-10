from __future__ import annotations

import json
import os
import re
from typing import Any

from openai import OpenAI


def _extract_json_object(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"^\s*```(?:json)?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*```\s*$", "", t)
    start = t.find("{")
    end = t.rfind("}")
    if start < 0 or end < 0 or end <= start:
        raise ValueError("Model output does not contain valid JSON object.")
    return t[start : end + 1]


def _client() -> OpenAI:
    key = os.getenv("ZHIPU_API_KEY")
    if not key:
        raise RuntimeError("Missing ZHIPU_API_KEY.")
    return OpenAI(
        api_key=key,
        base_url=os.getenv("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/"),
    )


def generate_dsl_from_nl(user_msg: str) -> dict[str, Any]:
    model = os.getenv("ZHIPU_MODEL", "glm-4-flash")
    system = """
You convert CAD natural language into strict JSON DSL.
Output JSON only.

Schema:
{
  "version": "1.0",
  "unit": "mm|cm|m|in",
  "shape": "sphere|cylinder|box",
  "params": {}
}

Shape params:
- sphere: radius OR diameter
- cylinder: radius OR diameter, and height
- box: length, width, height

Rules:
- Be faithful to dimensions in prompt.
- For sphere/ball/球/球体 use shape=\"sphere\".
- Keep output minimal and deterministic.
"""
    client = _client()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_msg},
    ]
    last_err = None
    for _attempt in range(3):
        try:
            msg = client.chat.completions.create(
                model=model,
                temperature=0,
                messages=messages,
            )
            raw_text = msg.choices[0].message.content or ""
            return json.loads(_extract_json_object(raw_text))
        except Exception as exc:
            last_err = exc
            messages.append({"role": "assistant", "content": "Invalid previous JSON."})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Error: {type(exc).__name__}: {exc}\n"
                        "Return ONE valid JSON object only. "
                        "Do not output enum placeholders such as 'mm|cm|m|in'. "
                        "Use concrete values only."
                    ),
                }
            )
    raise RuntimeError(f"Failed to generate valid DSL JSON: {type(last_err).__name__}: {last_err}")
