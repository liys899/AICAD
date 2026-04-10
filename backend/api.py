import os
from flask import Flask, request, send_file
import json
from utils.download import get_donwload_string
from codex import generate_cq_obj
from utils.json import NumpyEncoder, sanitize_for_json
from utils.tessellate import tessellate
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
        id, obj = generate_cq_obj(query)
        converted_obj = tessellate([obj])
        safe = sanitize_for_json(converted_obj)
        return jsonify(
            {
                "id": id,
                "shapes": json.loads(json.dumps(safe, cls=NumpyEncoder)),
            }
        )
    except Exception as e:
        print(e)
        return jsonify({"error": f"Something went wrong.{e}"})

@cross_origin()
@app.route("/download", methods=["GET"])
def download():
    id = request.args.get("id")
    file_type = request.args.get("file_type")
    file_path = get_donwload_string(id, file_type)
    try:
        return send_file(file_path, as_attachment=True)
    except Exception as e:
        print(e)
        return jsonify({"error": f"Something went wrong.{e}"})


if __name__ == "__main__":
    app.run(debug=True, port=5001)
