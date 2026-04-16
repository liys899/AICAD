from __future__ import annotations
import json
import os
import re
import time
from pathlib import Path
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

_SCAD_INDEX_PATH = Path(__file__).resolve().parent / "openscad_vendor" / "scad_module_index.json"
_SCAD_MODULE_INDEX_CACHE: list[dict[str, Any]] | None = None


def _load_scad_module_index() -> list[dict[str, Any]]:
    global _SCAD_MODULE_INDEX_CACHE
    if _SCAD_MODULE_INDEX_CACHE is not None:
        return _SCAD_MODULE_INDEX_CACHE
    if not _SCAD_INDEX_PATH.exists():
        _SCAD_MODULE_INDEX_CACHE = []
        return _SCAD_MODULE_INDEX_CACHE
    try:
        payload = json.loads(_SCAD_INDEX_PATH.read_text(encoding="utf-8"))
        modules = payload.get("modules")
        if isinstance(modules, list):
            _SCAD_MODULE_INDEX_CACHE = [m for m in modules if isinstance(m, dict)]
        else:
            _SCAD_MODULE_INDEX_CACHE = []
    except Exception:
        _SCAD_MODULE_INDEX_CACHE = []
    return _SCAD_MODULE_INDEX_CACHE


def _build_library_candidates_block(chat_messages: list[dict[str, str]], limit: int = 12) -> str:
    modules = _load_scad_module_index()
    if not modules:
        return ""
    corpus = " ".join(
        str(m.get("content", "")).lower()
        for m in chat_messages
        if isinstance(m, dict) and isinstance(m.get("content"), str)
    )
    query_tokens = {t for t in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", corpus) if len(t) >= 3}
    scored: list[tuple[int, dict[str, Any]]] = []
    for m in modules:
        module_name = str(m.get("module", "")).lower()
        args = [str(a).lower() for a in (m.get("args") or []) if isinstance(a, str)]
        score = 0
        for tok in query_tokens:
            if tok in module_name:
                score += 3
            if any(tok in a for a in args):
                score += 1
        if score > 0:
            scored.append((score, m))
    if not scored:
        pick = modules[: min(limit, len(modules))]
    else:
        pick = [m for _, m in sorted(scored, key=lambda x: x[0], reverse=True)[:limit]]
    lines = [
        "Library_call candidate modules from local scad_module_index.json:",
        "If using shape=\"library_call\", prefer module names from this list and keep args aligned.",
    ]
    for m in pick:
        mod = str(m.get("module", ""))
        path = str(m.get("path", ""))
        args = m.get("args") or []
        args_s = ", ".join(str(a) for a in args) if args else "(no args)"
        lines.append(f"- {mod} | path={path} | args={args_s}")
    return "\n".join(lines)


def generate_dsl_from_messages(chat_messages: list[dict[str, str]]) -> dict[str, Any]:
    """chat_messages: OpenAI-style roles user|assistant only (no system)."""
    if not chat_messages:
        raise ValueError("messages is required.")
    model = os.getenv("ZHIPU_MODEL", "glm-4-flash")
    client = _client()
    api_messages: list[dict[str, str]] = [{"role": "system", "content": _DSL_SYSTEM}]
    candidates_block = _build_library_candidates_block(chat_messages)
    if candidates_block:
        api_messages.append({"role": "system", "content": candidates_block})
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
    for attempt in range(3):
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
            # Upstream model API may intermittently return 5xx; retry same payload directly.
            status = getattr(exc, "status_code", None)
            text = str(exc)
            is_retryable_upstream = status in {500, 502, 503, 504} or any(code in text for code in (" 500", " 502", " 503", " 504"))
            if is_retryable_upstream and attempt < 2:
                time.sleep(0.6 * (attempt + 1))
                continue
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
