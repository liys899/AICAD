import json
import numpy as np


def _is_ocp_like(obj):
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return False
    mod = getattr(type(obj), "__module__", "") or ""
    name = type(obj).__name__
    if "OCP." in mod or "OCC." in mod:
        return True
    if name.startswith(("TopoDS_", "gp_", "BRep", "Geom", "Bnd")):
        return True
    return False


def sanitize_for_json(obj):
    """Strip OCP/OCC and numpy types so structures are JSON-serializable."""
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, (list, tuple)):
        return [sanitize_for_json(x) for x in obj]
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if _is_ocp_like(v):
                continue
            out[k] = sanitize_for_json(v)
        return out
    if _is_ocp_like(obj):
        return None
    return obj


class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if _is_ocp_like(obj):
            return None
        return json.JSONEncoder.default(self, obj)
