from __future__ import annotations
import json
import os
import re
from typing import Any

from openai import OpenAI
from business_shapes import build_shape_enum, build_shape_params_block, build_shape_rules_block


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


_DSL_SYSTEM = """
You convert CAD natural language into strict JSON DSL.
Output JSON only.

Schema:
{{
  "version": "1.0",
  "unit": "mm|cm|m|in",
  "shape": "{shape_enum}",
  "params": {{}}
}}

Optional multi-part schema (for multiple solids):
{{
  "version": "1.0",
  "unit": "mm|cm|m|in",
  "parts": [
    {{ "shape": "...", "params": {{ ... }} }}
  ],
  "ops": [
    {{ "type": "transform", "name": "moveA", "target": "p0", "translate": [x,y,z], "rotate": [rx,ry,rz] }},
    {{ "type": "boolean", "name": "cut1", "kind": "difference", "targets": ["moveA", "p1"] }}
  ],
  "result": "cut1"
}}

Shape params:
{shape_params}

Rules:
- Be faithful to dimensions in prompt.
{shape_rules}
- Keep output minimal and deterministic.
- For mechanisms/assemblies, prefer parts[] + ops[] + result to describe operation sequence (transform and boolean refs).

Multi-turn:
- Assistant messages may contain a line [DSL_JSON] followed by the CURRENT model JSON. Use it as the baseline when the user asks to tweak dimensions or change shape.
- Always output ONE complete JSON object for the final solid after this turn (not a patch file). If the user only changes one number, keep other parameters from [DSL_JSON] when still applicable.
""".format(
    shape_enum=build_shape_enum(),
    shape_params=build_shape_params_block(),
    shape_rules=build_shape_rules_block(),
)


def generate_dsl_from_messages(chat_messages: list[dict[str, str]]) -> dict[str, Any]:
    """chat_messages: OpenAI-style roles user|assistant only (no system)."""
    if not chat_messages:
        raise ValueError("messages is required.")
    model = os.getenv("ZHIPU_MODEL", "glm-4-flash")
    client = _client()
    api_messages: list[dict[str, str]] = [{"role": "system", "content": _DSL_SYSTEM}]
    for m in chat_messages:
        role = (m.get("role") or "").strip().lower()
        content = m.get("content")
        if not content or not isinstance(content, str):
            continue
        if role not in ("user", "assistant"):
            continue
        api_messages.append({"role": role, "content": content})
    if len(api_messages) < 2:
        raise ValueError("At least one user message is required.")

    messages = api_messages
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
                        f"Error: {type(exc).__name__}: {exc}\\n"
                        "Return ONE valid JSON object only. "
                        "Do not output enum placeholders such as 'mm|cm|m|in'. "
                        "Use concrete values only."
                    ),
                }
            )
    raise RuntimeError(f"Failed to generate valid DSL JSON: {type(last_err).__name__}: {last_err}")


def generate_dsl_from_nl(user_msg: str) -> dict[str, Any]:
    return generate_dsl_from_messages([{"role": "user", "content": user_msg}])
