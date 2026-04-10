import os
from flask import Flask, request, send_file
from utils.download import get_donwload_string
from codex import generate_scad_bundle
from flask import jsonify
from flask_cors import CORS, cross_origin
from flask import request

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))


app = Flask(__name__)
cors = CORS(app)
app.config["CORS_HEADERS"] = "Content-Type"


@cross_origin()
@app.route("/cad", methods=["GET"])
def cad():
    try:
        query = request.args.get("query")
        data = generate_scad_bundle(query)
        return jsonify(data)
    except Exception as e:
        debug_id = request.args.get("debug_id") or "cad_error"
        return (
            jsonify(
                {
                    "error": {
                        "code": "CAD_GENERATION_FAILED",
                        "message": str(e),
                        "debug_id": debug_id,
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
