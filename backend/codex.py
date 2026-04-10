import json
import os
from datetime import datetime

from dotenv import load_dotenv

from dsl_schema import normalize_dsl
from dsl_to_scad import dsl_to_scad
from nl_to_dsl import generate_dsl_from_nl

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


def generate_scad_bundle(user_msg: str) -> dict:
    if not user_msg:
        raise ValueError("query is required.")
    pipeline = os.getenv("CQASK_PIPELINE", "scad").strip().lower()
    if pipeline != "scad":
        raise RuntimeError("Only CQASK_PIPELINE=scad is supported in this release.")
    # Reserved emergency switch. Legacy pipeline is intentionally disabled by default.
    if os.getenv("CQASK_ENABLE_LEGACY_FALLBACK", "false").strip().lower() == "true":
        raise RuntimeError("Legacy CadQuery prompt pipeline has been deprecated.")
    _ensure_out_dir()

    dsl_raw = generate_dsl_from_nl(user_msg)
    dsl = normalize_dsl(dsl_raw)
    scad_script, params_meta = dsl_to_scad(dsl)

    model_id = datetime.now().strftime("%Y-%m-%dT%H-%M-%S.%f")
    scad_path = os.path.join(_GENERATED_SCAD_DIR, f"{model_id}.scad")
    dsl_path = os.path.join(_GENERATED_SCAD_DIR, f"{model_id}.json")
    with open(scad_path, "w", encoding="utf-8") as f:
        f.write(scad_script.strip() + "\n")
    with open(dsl_path, "w", encoding="utf-8") as f:
        json.dump({"history": [user_msg], "dsl": dsl.to_dict(), "paramsMeta": params_meta}, f, ensure_ascii=False, indent=2)
    _cleanup_generated_scad_files(_MAX_GENERATED_FILES)

    return {
        "id": model_id,
        "apiVersion": "scad-v1",
        "pipeline": "scad",
        "dsl": dsl.to_dict(),
        "scad": scad_script,
        "paramsMeta": params_meta,
    }
