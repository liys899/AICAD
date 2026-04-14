from __future__ import annotations

from dataclasses import dataclass
import re
from business_shapes import SHAPE_ALIASES, supported_shapes_set


_UNIT_TO_MM = {
    "mm": 1.0,
    "millimeter": 1.0,
    "millimeters": 1.0,
    "cm": 10.0,
    "centimeter": 10.0,
    "centimeters": 10.0,
    "m": 1000.0,
    "meter": 1000.0,
    "meters": 1000.0,
    "in": 25.4,
    "inch": 25.4,
    "inches": 25.4,
}

_SUPPORTED_SHAPES = supported_shapes_set()
_NUM_WITH_UNIT_RE = re.compile(
    r"^\s*(?P<val>-?\d+(?:\.\d+)?)\s*(?P<unit>mm|cm|m|in|inch|inches|millimeter|millimeters|centimeter|centimeters|meter|meters)?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NormalizedDsl:
    version: str
    unit: str
    shape: str
    params: dict
    parts: list[dict] | None = None
    ops: list[dict] | None = None
    result: str | None = None

    def to_dict(self) -> dict:
        out = {
            "version": self.version,
            "unit": self.unit,
            "shape": self.shape,
            "params": self.params,
        }
        if self.parts is not None:
            out["parts"] = self.parts
        if self.ops is not None:
            out["ops"] = self.ops
        if self.result is not None:
            out["result"] = self.result
        return out


def _to_pos_float(value, field_name: str, factor: float) -> float:
    try:
        used_inline_unit = False
        if isinstance(value, str):
            m = _NUM_WITH_UNIT_RE.match(value)
            if m:
                fv = float(m.group("val"))
                u = (m.group("unit") or "").lower()
                if u:
                    fv *= _UNIT_TO_MM.get(u, 1.0)
                    used_inline_unit = True
            else:
                fv = float(value)
        else:
            fv = float(value)
        if not used_inline_unit:
            fv *= factor
    except Exception as exc:
        raise ValueError(f"Invalid number for '{field_name}': {value}") from exc
    if fv <= 0:
        raise ValueError(f"'{field_name}' must be > 0.")
    return fv


def _to_int_teeth(value, field_name: str) -> int:
    try:
        if isinstance(value, str):
            value = value.strip()
        teeth = int(round(float(value)))
    except Exception as exc:
        raise ValueError(f"Invalid integer for '{field_name}': {value}") from exc
    if teeth < 3 or teeth > 512:
        raise ValueError(f"'{field_name}' must be between 3 and 512.")
    return teeth


def _to_int_sides(value, field_name: str, lo: int = 3, hi: int = 64) -> int:
    try:
        if isinstance(value, str):
            value = value.strip()
        n = int(round(float(value)))
    except Exception as exc:
        raise ValueError(f"Invalid integer for '{field_name}': {value}") from exc
    if n < lo or n > hi:
        raise ValueError(f"'{field_name}' must be between {lo} and {hi}.")
    return n


def _normalize_single(shape_raw: str, params_raw: dict, factor: float) -> tuple[str, dict]:
    shape = str(shape_raw).strip().lower()
    shape = SHAPE_ALIASES.get(shape, shape)
    if shape not in _SUPPORTED_SHAPES and "|" in shape:
        tokens = [x.strip() for x in shape.split("|") if x.strip()]
        for t in tokens:
            if t in _SUPPORTED_SHAPES:
                shape = t
                break
    if shape not in _SUPPORTED_SHAPES:
        raise ValueError(f"Unsupported shape '{shape}'. Allowed: {sorted(_SUPPORTED_SHAPES)}")
    if not isinstance(params_raw, dict):
        raise ValueError("DSL 'params' must be an object.")
    params = params_raw
    out_params: dict = {}
    if shape == "sphere":
        if "radius" in params:
            out_params["radius"] = _to_pos_float(params["radius"], "radius", factor)
        elif "diameter" in params:
            out_params["radius"] = _to_pos_float(params["diameter"], "diameter", factor) / 2.0
        else:
            raise ValueError("Sphere requires 'radius' or 'diameter'.")
    elif shape == "cylinder":
        if "radius" in params:
            out_params["radius"] = _to_pos_float(params["radius"], "radius", factor)
        elif "diameter" in params:
            out_params["radius"] = _to_pos_float(params["diameter"], "diameter", factor) / 2.0
        else:
            raise ValueError("Cylinder requires 'radius' or 'diameter'.")
        out_params["height"] = _to_pos_float(params.get("height"), "height", factor)
    elif shape == "box":
        out_params["length"] = _to_pos_float(params.get("length"), "length", factor)
        out_params["width"] = _to_pos_float(params.get("width"), "width", factor)
        out_params["height"] = _to_pos_float(params.get("height"), "height", factor)
    elif shape == "shaft":
        if "radius" in params:
            out_params["radius"] = _to_pos_float(params["radius"], "radius", factor)
        elif "diameter" in params:
            out_params["radius"] = _to_pos_float(params["diameter"], "diameter", factor) / 2.0
        else:
            raise ValueError("shaft requires 'radius' or 'diameter'.")
        raw_len = params.get("length", params.get("height", params.get("l")))
        out_params["length"] = _to_pos_float(raw_len, "length", factor)
    elif shape == "hollow_shaft":
        outer = params.get("outer_radius", params.get("r_outer", params.get("radius")))
        if outer is None and "outer_diameter" in params:
            outer = _to_pos_float(params["outer_diameter"], "outer_diameter", factor) / 2.0
        elif outer is None and "diameter" in params:
            outer = _to_pos_float(params["diameter"], "diameter", factor) / 2.0
        else:
            outer = _to_pos_float(outer, "outer_radius", factor) if outer is not None else None
        if outer is None:
            raise ValueError("hollow_shaft requires 'outer_radius' or 'outer_diameter'.")
        inner = params.get("inner_radius", params.get("r_inner"))
        if inner is None and "inner_diameter" in params:
            inner = _to_pos_float(params["inner_diameter"], "inner_diameter", factor) / 2.0
        elif inner is None:
            raise ValueError("hollow_shaft requires 'inner_radius' or 'inner_diameter'.")
        else:
            inner = _to_pos_float(inner, "inner_radius", factor)
        if inner >= outer:
            raise ValueError("hollow_shaft requires inner radius < outer radius.")
        raw_len = params.get("length", params.get("height", params.get("l")))
        out_params["outer_radius"] = outer
        out_params["inner_radius"] = inner
        out_params["length"] = _to_pos_float(raw_len, "length", factor)
    elif shape == "stepped_shaft":
        if "radius1" in params:
            r1 = _to_pos_float(params["radius1"], "radius1", factor)
        elif "diameter1" in params:
            r1 = _to_pos_float(params["diameter1"], "diameter1", factor) / 2.0
        else:
            raise ValueError("stepped_shaft requires 'radius1' or 'diameter1'.")
        if "radius2" in params:
            r2 = _to_pos_float(params["radius2"], "radius2", factor)
        elif "diameter2" in params:
            r2 = _to_pos_float(params["diameter2"], "diameter2", factor) / 2.0
        else:
            raise ValueError("stepped_shaft requires 'radius2' or 'diameter2'.")
        l1_raw = params.get("length1", params.get("height1", params.get("l1")))
        l2_raw = params.get("length2", params.get("height2", params.get("l2")))
        out_params["radius1"] = r1
        out_params["length1"] = _to_pos_float(l1_raw, "length1", factor)
        out_params["radius2"] = r2
        out_params["length2"] = _to_pos_float(l2_raw, "length2", factor)
    elif shape == "spur_gear":
        raw_teeth = params.get("teeth", params.get("tooth_count", params.get("z")))
        if raw_teeth is None:
            raise ValueError("spur_gear requires integer 'teeth' (number of teeth).")
        out_params["teeth"] = _to_int_teeth(raw_teeth, "teeth")
        mod_key = params.get("module", params.get("pitch_module", params.get("m")))
        if mod_key is None:
            raise ValueError("spur_gear requires 'module' (gear module in mm, e.g. 1, 1.5, 2).")
        out_params["pitch_module"] = _to_pos_float(mod_key, "module", factor)
        fw = params.get("width", params.get("face_width", params.get("thickness")))
        if fw is None:
            raise ValueError("spur_gear requires 'width' (face width in mm).")
        out_params["face_width"] = _to_pos_float(fw, "width", factor)
        pa = params.get("pressure_angle", 20)
        out_params["pressure_angle"] = float(_to_pos_float(pa, "pressure_angle", 1.0))
    elif shape == "regular_prism":
        raw_sides = params.get("sides", params.get("n", params.get("face_count")))
        if raw_sides is None:
            raise ValueError("regular_prism requires integer 'sides' (number of base edges, >=3).")
        out_params["sides"] = _to_int_sides(raw_sides, "sides", 3, 64)
        r = params.get("radius", params.get("circumradius", params.get("r")))
        if r is None:
            raise ValueError("regular_prism requires 'radius' (mm, circumradius of base polygon).")
        out_params["radius"] = _to_pos_float(r, "radius", factor)
        out_params["height"] = _to_pos_float(params.get("height"), "height", factor)
    elif shape == "regular_pyramid":
        raw_sides = params.get("sides", params.get("n", params.get("face_count")))
        if raw_sides is None:
            raise ValueError("regular_pyramid requires integer 'sides' (number of base edges, >=3).")
        out_params["sides"] = _to_int_sides(raw_sides, "sides", 3, 64)
        r = params.get("radius", params.get("circumradius", params.get("r")))
        if r is None:
            raise ValueError("regular_pyramid requires 'radius' (mm, circumradius of base polygon).")
        out_params["radius"] = _to_pos_float(r, "radius", factor)
        out_params["height"] = _to_pos_float(params.get("height"), "height", factor)
    return shape, out_params


def normalize_dsl(raw: dict) -> NormalizedDsl:
    if not isinstance(raw, dict):
        raise ValueError("DSL must be a JSON object.")

    unit = str(raw.get("unit", "mm")).strip().lower()
    if unit not in _UNIT_TO_MM and "|" in unit:
        unit = "mm"
    if unit not in _UNIT_TO_MM:
        raise ValueError(f"Unsupported unit '{unit}'.")
    factor = _UNIT_TO_MM[unit]

    raw_parts = raw.get("parts")
    if isinstance(raw_parts, list):
        if len(raw_parts) == 0:
            raise ValueError("DSL 'parts' must not be empty.")
        out_parts: list[dict] = []
        for idx, item in enumerate(raw_parts):
            if not isinstance(item, dict):
                raise ValueError(f"DSL parts[{idx}] must be an object.")
            p_unit = str(item.get("unit", unit)).strip().lower()
            if p_unit not in _UNIT_TO_MM:
                raise ValueError(f"Unsupported unit '{p_unit}' in parts[{idx}].")
            part_shape, part_params = _normalize_single(
                item.get("shape", ""),
                item.get("params"),
                _UNIT_TO_MM[p_unit],
            )
            out_parts.append({"shape": part_shape, "params": part_params, "unit": "mm"})
        raw_ops = raw.get("ops")
        out_ops: list[dict] | None = None
        if raw_ops is not None:
            if not isinstance(raw_ops, list):
                raise ValueError("DSL 'ops' must be an array.")
            out_ops = []
            for idx, item in enumerate(raw_ops):
                if not isinstance(item, dict):
                    raise ValueError(f"DSL ops[{idx}] must be an object.")
                op_type = str(item.get("type", "")).strip().lower()
                if op_type not in {"transform", "boolean"}:
                    raise ValueError("op.type must be 'transform' or 'boolean'.")
                name = str(item.get("name", f"op{idx}")).strip()
                if not name:
                    raise ValueError(f"ops[{idx}] name must not be empty.")
                if op_type == "transform":
                    target = str(item.get("target", "")).strip()
                    if not target:
                        raise ValueError(f"ops[{idx}] transform requires non-empty 'target'.")
                    translate = item.get("translate", [0, 0, 0])
                    rotate = item.get("rotate", [0, 0, 0])
                    if not isinstance(translate, list) or len(translate) != 3:
                        raise ValueError(f"ops[{idx}] translate must be [x,y,z].")
                    if not isinstance(rotate, list) or len(rotate) != 3:
                        raise ValueError(f"ops[{idx}] rotate must be [rx,ry,rz].")
                    out_ops.append(
                        {
                            "type": "transform",
                            "name": name,
                            "target": target,
                            "translate": [float(translate[0]), float(translate[1]), float(translate[2])],
                            "rotate": [float(rotate[0]), float(rotate[1]), float(rotate[2])],
                        }
                    )
                else:
                    kind = str(item.get("kind", "")).strip().lower()
                    if kind not in {"union", "difference", "intersection"}:
                        raise ValueError("boolean kind must be union|difference|intersection.")
                    targets = item.get("targets")
                    if not isinstance(targets, list) or len(targets) < 2:
                        raise ValueError(f"ops[{idx}] boolean requires 'targets' with at least 2 refs.")
                    out_targets = [str(x).strip() for x in targets if str(x).strip()]
                    if len(out_targets) < 2:
                        raise ValueError(f"ops[{idx}] boolean targets must contain at least 2 non-empty refs.")
                    out_ops.append(
                        {
                            "type": "boolean",
                            "name": name,
                            "kind": kind,
                            "targets": out_targets,
                        }
                    )
        out_result = raw.get("result")
        if out_result is not None:
            out_result = str(out_result).strip()
            if not out_result:
                out_result = None
        return NormalizedDsl(
            version=str(raw.get("version", "1.0")),
            unit="mm",
            shape="assembly",
            params={},
            parts=out_parts,
            ops=out_ops,
            result=out_result,
        )

    shape, out_params = _normalize_single(raw.get("shape", ""), raw.get("params"), factor)

    return NormalizedDsl(
        version=str(raw.get("version", "1.0")),
        unit="mm",
        shape=shape,
        params=out_params,
    )
