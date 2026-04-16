import os
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS, cross_origin

from codex import generate_scad_bundle
from utils.download import get_donwload_string

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))


app = Flask(__name__)
cors = CORS(app)
app.config["CORS_HEADERS"] = "Content-Type"


def _parse_cad_messages(body: dict | None) -> list[dict[str, str]] | None:
    if not body:
        return None
    raw = body.get("messages")
    if not isinstance(raw, list):
        return None
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).strip().lower()
        content = item.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        text = content.strip()
        if not text:
            continue
        out.append({"role": role, "content": text})
    return out or None


def _parse_cad_dsl(body: dict | None) -> dict | None:
    if not isinstance(body, dict):
        return None
    direct = body.get("dsl")
    if isinstance(direct, dict):
        return direct
    # Allow posting DSL object directly to /cad
    if isinstance(body.get("parts"), list):
        return body
    if isinstance(body.get("shape"), str) and isinstance(body.get("params"), dict):
        return body
    return None


@cross_origin()
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "service": "cqask-backend"})


@cross_origin()
@app.route("/cad", methods=["GET", "POST"])
def cad():
    try:
        if request.method == "POST":
            body = request.get_json(force=True, silent=True)
            dsl = _parse_cad_dsl(body if isinstance(body, dict) else None)
            if dsl:
                data = generate_scad_bundle(dsl_raw=dsl)
                return jsonify(data)
            msgs = _parse_cad_messages(body if isinstance(body, dict) else None)
            if msgs:
                data = generate_scad_bundle(messages=msgs)
            else:
                query = (body or {}).get("query") if isinstance(body, dict) else None
                if not query and isinstance(body, dict):
                    query = body.get("message")
                if not query:
                    return (
                        jsonify(
                            {
                                "error": {
                                    "code": "BAD_REQUEST",
                                    "message": "Provide JSON { \"dsl\": {...} } or { \"messages\": [...] } or { \"query\": \"...\" }.",
                                    "debug_id": "cad_bad_request",
                                }
                            }
                        ),
                        400,
                    )
                data = generate_scad_bundle(user_msg=str(query))
        else:
            query = request.args.get("query")
            data = generate_scad_bundle(user_msg=query or "")
        return jsonify(data)
    except Exception as e:
        return (
            jsonify(
                {
                    "error": {
                        "code": "CAD_GENERATION_FAILED",
                        "message": str(e),
                        "debug_id": "cad_error",
                    }
                }
            ),
            400,
        )


@cross_origin()
@app.route("/download", methods=["GET"])
def download():
    id = request.args.get("id")
    file_type = request.args.get("file_type")
    try:
        file_path = get_donwload_string(id, file_type)
        return send_file(file_path, as_attachment=True)
    except Exception as e:
        return jsonify({"error": {"code": "DOWNLOAD_FAILED", "message": str(e)}}), 400


@cross_origin()
@app.route("/standards/fasteners", methods=["GET"])
def standards_fasteners():
    """
    Lightweight "parameter library" manifest for industrial fasteners.

    The actual dimensional tables live inside BOSL2 (vendored under backend/openscad_vendor/BOSL2/).
    This endpoint tells the UI how to call BOSL2's standard screw generator via DSL `shape=library_call`.
    """
    return jsonify(
        {
            "vendor": "BOSL2",
            "recommended_dsl": {
                "version": "1.0",
                "unit": "mm",
                "shape": "library_call",
                "params": {
                    "module": "screw",
                    "include_mode": "include",
                    "library_paths": [
                        "openscad_vendor/BOSL2/std.scad",
                        "openscad_vendor/BOSL2/screws.scad",
                    ],
                    "args": {
                        "spec": "M8,40",
                        "head": "hex",
                        "drive": "none",
                        "thread": "coarse",
                        "details": True,
                    },
                },
            },
            "spec_format": {
                "metric_examples": ["M8", "M8x1.25", "M8,40", "M8x1.25,40"],
                "notes": [
                    "If length is omitted in spec, pass length=... (mm) in args.",
                    "If pitch is omitted, BOSL2 uses standard pitch for the diameter (default coarse).",
                ],
            },
            "thread_options": ["coarse", "fine", "extrafine", "superfine", "none", True, False, 1.25],
            "head_options": [
                "none",
                "hex",
                "socket",
                "button",
                "flat",
                "flat sharp",
                "pan",
                "cheese",
            ],
            "drive_options": [
                "none",
                "hex",
                "slot",
                "phillips",
                "torx",
                "t20",
            ],
        }
    )


if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "false").strip().lower() == "true"
    # Disable auto-reloader by default to avoid proxy socket hang-up during requests.
    app.run(debug=debug, port=5001, use_reloader=False, threaded=True)
