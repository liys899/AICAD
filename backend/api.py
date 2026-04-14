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


if __name__ == "__main__":
    app.run(debug=True, port=5001)
