import json
import os
from datetime import datetime

from dotenv import load_dotenv

from dsl_schema import NormalizedDsl, normalize_dsl
from dsl_to_scad import dsl_to_scad
from nl_to_dsl import generate_dsl_from_messages, generate_dsl_from_nl

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
        dsl_raw = generate_dsl_from_messages(messages)
        history_payload = {"messages": messages}
    elif user_msg:
        dsl_raw = generate_dsl_from_nl(user_msg)
        history_payload = {"messages": [{"role": "user", "content": user_msg}]}
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
