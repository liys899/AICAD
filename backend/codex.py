import json
import os
from datetime import datetime

from dotenv import load_dotenv

from dsl_schema import NormalizedDsl, normalize_dsl
from dsl_validator import validate_relationship_consistency
from dsl_to_scad import dsl_to_scad
from nl_to_dsl import generate_dsl_from_messages
from relationship_parser import build_relationship_guidance, parse_relationships_from_messages

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))


_GENERATED_SCAD_DIR = "generated_scad"
_MAX_GENERATED_FILES = 20


def _ensure_out_dir() -> None:
    if not os.path.exists(_GENERATED_SCAD_DIR):
        os.makedirs(_GENERATED_SCAD_DIR)


def _cleanup_generated_scad_files(max_files: int = _MAX_GENERATED_FILES) -> None:
    if max_files <= 0 or not os.path.isdir(_GENERATED_SCAD_DIR):
        return
    try:
        files = []
        for name in os.listdir(_GENERATED_SCAD_DIR):
            p = os.path.join(_GENERATED_SCAD_DIR, name)
            if os.path.isfile(p):
                files.append(p)
        if len(files) <= max_files:
            return
        files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        for p in files[max_files:]:
            try:
                os.remove(p)
            except OSError:
                pass
    except OSError:
        pass


def _reply_line_cn(dsl: NormalizedDsl) -> str:
    if dsl.shape == "assembly":
        part_count = len(dsl.parts or [])
        op_count = len(dsl.ops or [])
        if op_count > 0:
            return f"已生成组合体（{part_count} 个实体，{op_count} 个操作，单位按 {dsl.unit} 换算为毫米）。"
        return f"已生成组合体（包含 {part_count} 个实体，单位按 {dsl.unit} 换算为毫米）。"
    labels = {
        "sphere": "球体",
        "cylinder": "圆柱体",
        "box": "长方体",
        "shaft": "实心轴",
        "hollow_shaft": "空心轴/套筒",
        "stepped_shaft": "台阶轴",
        "spur_gear": "直齿圆柱齿轮（MCAD 渐开线参考）",
        "spur_gear_pair": "啮合直齿轮对",
        "bearing_608": "608 深沟球轴承",
        "bearing_6204": "6204 深沟球轴承",
        "hex_nut_iso4032": "六角螺母（ISO4032）",
        "hex_bolt_iso4017": "六角头螺栓（ISO4017）",
        "plain_washer_iso7089": "平垫圈（ISO7089）",
        "regular_prism": "正棱柱（正多边形底 + 拉伸）",
        "regular_pyramid": "正棱锥（正多边形底 + 锥顶）",
    }
    name = labels.get(dsl.shape, dsl.shape)
    parts = []
    for k, v in dsl.params.items():
        if k in ("teeth", "sides"):
            parts.append(f"{k}={int(v)}")
        else:
            parts.append(f"{k}={v}")
    detail = "，".join(parts) if parts else ""
    return f"已生成{name}（{detail}，单位按 {dsl.unit} 换算为毫米）。"


def _repair_relationship_candidate(dsl_raw: dict, relations: list[str]) -> dict:
    if not isinstance(dsl_raw, dict):
        return dsl_raw
    if "gear_mesh" not in relations:
        return dsl_raw
    parts = dsl_raw.get("parts")
    if not isinstance(parts, list) or len(parts) < 2:
        return dsl_raw
    spur_idxs = [i for i, p in enumerate(parts) if isinstance(p, dict) and str(p.get("shape", "")).strip().lower() == "spur_gear"]
    if len(spur_idxs) < 2:
        return dsl_raw

    # Force assembly shape for multi-part relation candidates.
    dsl_raw["shape"] = "assembly"
    dsl_raw["params"] = {}

    ops = dsl_raw.get("ops")
    if not isinstance(ops, list):
        ops = []
    fixed_ops: list[dict] = []
    used_targets: set[str] = set()
    def _vec3(value) -> list[float]:
        if isinstance(value, list):
            vals = value[:3]
        elif isinstance(value, tuple):
            vals = list(value[:3])
        else:
            vals = []
        out: list[float] = []
        for i in range(3):
            try:
                out.append(float(vals[i]))
            except Exception:
                out.append(0.0)
        return out

    for idx, op in enumerate(ops):
        if not isinstance(op, dict):
            continue
        typ = str(op.get("type", "")).strip().lower()
        if typ == "transform":
            target = str(op.get("target", "")).strip()
            if not target:
                for sp_idx in spur_idxs:
                    candidate = f"p{sp_idx}"
                    if candidate not in used_targets:
                        target = candidate
                        break
                if not target:
                    target = f"p{spur_idxs[0]}"
            used_targets.add(target)
            fixed_ops.append(
                {
                    "type": "transform",
                    "name": str(op.get("name", f"move{idx}")).strip() or f"move{idx}",
                    "target": target,
                    "translate": _vec3(op.get("translate", [0, 0, 0])),
                    "rotate": _vec3(op.get("rotate", [0, 0, 0])),
                }
            )
        elif typ == "boolean":
            fixed_ops.append(op)

    # If model omitted transforms, create deterministic gear-pair placement.
    if not any(str(op.get("type", "")).strip().lower() == "transform" for op in fixed_ops):
        p0 = parts[spur_idxs[0]].get("params", {}) if isinstance(parts[spur_idxs[0]], dict) else {}
        p1 = parts[spur_idxs[1]].get("params", {}) if isinstance(parts[spur_idxs[1]], dict) else {}
        try:
            m0 = float(p0.get("module", p0.get("pitch_module", 1.0)))
            m1 = float(p1.get("module", p1.get("pitch_module", m0)))
            z0 = float(p0.get("teeth", 20))
            z1 = float(p1.get("teeth", 40))
            mod = m0 if m0 > 0 else m1
            center_dist = mod * (z0 + z1) / 2.0
        except Exception:
            center_dist = 40.0
        fixed_ops.extend(
            [
                {"type": "transform", "name": "moveA", "target": f"p{spur_idxs[0]}", "translate": [0, 0, 0], "rotate": [0, 0, 0]},
                {"type": "transform", "name": "moveB", "target": f"p{spur_idxs[1]}", "translate": [center_dist, 0, 0], "rotate": [0, 0, 0]},
                {"type": "boolean", "name": "mesh_union", "kind": "union", "targets": ["moveA", "moveB"]},
            ]
        )
        dsl_raw["result"] = "mesh_union"

    dsl_raw["ops"] = fixed_ops

    if "coaxial" in relations:
        parts = dsl_raw.get("parts")
        if isinstance(parts, list) and len(parts) >= 2:
            dsl_raw["shape"] = "assembly"
            dsl_raw["params"] = {}
            raw_ops = dsl_raw.get("ops")
            ops = raw_ops if isinstance(raw_ops, list) else []
            existing_targets = {
                str(op.get("target", "")).strip().lower()
                for op in ops
                if isinstance(op, dict) and str(op.get("type", "")).strip().lower() == "transform"
            }
            for idx in range(len(parts)):
                pref = f"p{idx}"
                if pref in existing_targets:
                    continue
                ops.append(
                    {
                        "type": "transform",
                        "name": f"coaxial_p{idx}",
                        "target": pref,
                        "translate": [0.0, 0.0, 0.0],
                        "rotate": [0.0, 0.0, 0.0],
                    }
                )
            if not dsl_raw.get("result") and ops:
                dsl_raw["result"] = str(ops[0].get("name", "coaxial_p0"))
            dsl_raw["ops"] = ops

    return dsl_raw


def _repair_through_hole_candidate(dsl_raw: dict, relations: list[str]) -> dict:
    if not isinstance(dsl_raw, dict):
        return dsl_raw
    if "through_hole" not in relations:
        return dsl_raw
    parts = dsl_raw.get("parts")
    ops = dsl_raw.get("ops")
    if not isinstance(parts, list) or not isinstance(ops, list) or len(parts) < 2:
        return dsl_raw

    def _shape_of(idx: int) -> str:
        if idx < 0 or idx >= len(parts):
            return ""
        item = parts[idx]
        if not isinstance(item, dict):
            return ""
        return str(item.get("shape", "")).strip().lower()

    def _part_idx_from_ref(ref: str) -> int | None:
        token = str(ref or "").strip().lower()
        if token.startswith("p") and token[1:].isdigit():
            idx = int(token[1:])
            return idx if 0 <= idx < len(parts) else None
        if token.startswith("part_") and token[5:].isdigit():
            idx = int(token[5:])
            return idx if 0 <= idx < len(parts) else None
        if token.startswith("part") and token[4:].isdigit():
            idx = int(token[4:])
            return idx if 0 <= idx < len(parts) else None
        if token.isdigit():
            idx = int(token)
            return idx if 0 <= idx < len(parts) else None
        for i, p in enumerate(parts):
            if not isinstance(p, dict):
                continue
            if str(p.get("shape", "")).strip().lower() == token:
                return i
        return None

    for op in ops:
        if not isinstance(op, dict):
            continue
        if str(op.get("type", "")).strip().lower() != "boolean":
            continue
        if str(op.get("kind", "")).strip().lower() != "difference":
            continue
        targets = op.get("targets")
        if not isinstance(targets, list) or len(targets) < 2:
            continue

        base_idx = _part_idx_from_ref(str(targets[0]))
        tool_idx = _part_idx_from_ref(str(targets[1]))
        if base_idx is None or tool_idx is None or base_idx == tool_idx:
            continue

        base_shape = _shape_of(base_idx)
        tool_shape = _shape_of(tool_idx)
        solid_shapes = {"shaft", "box", "cylinder", "sphere", "stepped_shaft", "regular_prism", "regular_pyramid", "spur_gear"}
        hole_like_shapes = {"hollow_shaft", "cylinder"}

        # Fix accidental reverse order: difference(tool, base) -> difference(base, tool)
        if base_shape in hole_like_shapes and tool_shape in solid_shapes:
            targets[0], targets[1] = targets[1], targets[0]
            base_idx, tool_idx = tool_idx, base_idx
            base_shape, tool_shape = tool_shape, base_shape
        # Canonicalize to stable part refs so later part-shape rewrites do not break op targets.
        targets[0] = f"p{base_idx}"
        targets[1] = f"p{tool_idx}"

        # through_hole cutter should be a simple cylinder (radius=hole_radius, length>=base length)
        if tool_shape == "hollow_shaft":
            tool = parts[tool_idx] if isinstance(parts[tool_idx], dict) else {}
            tparams = tool.get("params", {}) if isinstance(tool.get("params"), dict) else {}
            inner_r = tparams.get("inner_radius", tparams.get("radius", 1.0))
            try:
                hole_r = float(inner_r)
            except Exception:
                hole_r = 1.0
            base = parts[base_idx] if isinstance(parts[base_idx], dict) else {}
            bparams = base.get("params", {}) if isinstance(base.get("params"), dict) else {}
            base_len = bparams.get("length", bparams.get("height", 20.0))
            try:
                cutter_h = max(float(base_len) + 0.2, float(tparams.get("length", base_len)) + 0.2)
            except Exception:
                cutter_h = 20.2
            parts[tool_idx] = {"shape": "cylinder", "params": {"radius": hole_r, "height": cutter_h}}
        elif tool_shape == "cylinder":
            # Ensure cutter is long enough to pass through target body.
            tool = parts[tool_idx] if isinstance(parts[tool_idx], dict) else {}
            tparams = tool.get("params", {}) if isinstance(tool.get("params"), dict) else {}
            base = parts[base_idx] if isinstance(parts[base_idx], dict) else {}
            bparams = base.get("params", {}) if isinstance(base.get("params"), dict) else {}
            base_len = bparams.get("length", bparams.get("height", None))
            if base_len is not None:
                try:
                    need_h = float(base_len) + 0.2
                    cur_h = float(tparams.get("height", need_h))
                    if cur_h < need_h:
                        tparams["height"] = need_h
                        tool["params"] = tparams
                        parts[tool_idx] = tool
                except Exception:
                    pass
    dsl_raw["parts"] = parts
    dsl_raw["ops"] = ops
    return dsl_raw


def generate_scad_bundle(
    user_msg: str | None = None,
    messages: list[dict[str, str]] | None = None,
    dsl_raw: dict | None = None,
) -> dict:
    pipeline = os.getenv("CQASK_PIPELINE", "scad").strip().lower()
    if pipeline != "scad":
        raise RuntimeError("Only CQASK_PIPELINE=scad is supported in this release.")
    if os.getenv("CQASK_ENABLE_LEGACY_FALLBACK", "false").strip().lower() == "true":
        raise RuntimeError("Legacy CadQuery prompt pipeline has been deprecated.")
    _ensure_out_dir()

    if isinstance(dsl_raw, dict):
        history_payload = {"source": "dsl"}
    elif messages is not None and len(messages) > 0:
        dsl_raw, used_messages = _generate_dsl_with_relationship_loop(messages)
        history_payload = {"messages": used_messages}
    elif user_msg:
        base_messages = [{"role": "user", "content": user_msg}]
        dsl_raw, used_messages = _generate_dsl_with_relationship_loop(base_messages)
        history_payload = {"messages": used_messages}
    else:
        raise ValueError("query or messages or dsl is required.")

    dsl = normalize_dsl(dsl_raw)
    scad_script, params_meta = dsl_to_scad(dsl)
    reply = _reply_line_cn(dsl)

    model_id = datetime.now().strftime("%Y-%m-%dT%H-%M-%S.%f")
    scad_path = os.path.join(_GENERATED_SCAD_DIR, f"{model_id}.scad")
    dsl_path = os.path.join(_GENERATED_SCAD_DIR, f"{model_id}.json")
    with open(scad_path, "w", encoding="utf-8") as f:
        f.write(scad_script.strip() + "\n")
    with open(dsl_path, "w", encoding="utf-8") as f:
        json.dump(
            {**history_payload, "dsl": dsl.to_dict(), "paramsMeta": params_meta, "reply": reply},
            f,
            ensure_ascii=False,
            indent=2,
        )
    _cleanup_generated_scad_files(_MAX_GENERATED_FILES)

    return {
        "id": model_id,
        "apiVersion": "scad-v1",
        "pipeline": "scad",
        "dsl": dsl.to_dict(),
        "scad": scad_script,
        "paramsMeta": params_meta,
        "reply": reply,
    }


def _generate_dsl_with_relationship_loop(messages: list[dict[str, str]]) -> tuple[dict, list[dict[str, str]]]:
    work_messages = list(messages)
    rel_spec = parse_relationships_from_messages(work_messages)
    guidance = build_relationship_guidance(rel_spec)
    if guidance:
        work_messages = [
            *work_messages,
            {"role": "assistant", "content": "[RELATIONSHIP_HINTS]\n" + guidance},
            {"role": "user", "content": "Use these relationship hints strictly when generating final DSL JSON."},
        ]

    last_err: Exception | None = None
    for _attempt in range(3):
        try:
            dsl_raw = generate_dsl_from_messages(work_messages)
            dsl_raw = _repair_relationship_candidate(dsl_raw, rel_spec.relations)
            dsl_raw = _repair_through_hole_candidate(dsl_raw, rel_spec.relations)
            dsl = normalize_dsl(dsl_raw)
            validate_relationship_consistency(dsl, rel_spec)
            return dsl_raw, work_messages
        except Exception as exc:
            last_err = exc
            work_messages = [
                *work_messages,
                {"role": "assistant", "content": f"Previous candidate failed validation: {type(exc).__name__}: {exc}"},
                {
                    "role": "user",
                    "content": (
                        "Regenerate ONE complete DSL JSON and satisfy all relationship constraints exactly. "
                        "Do not explain."
                    ),
                },
            ]
    raise RuntimeError(f"Failed to generate relationship-consistent DSL: {type(last_err).__name__}: {last_err}")
