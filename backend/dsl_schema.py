from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
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
_SCAD_INDEX_PATH = Path(__file__).resolve().parent / "openscad_vendor" / "scad_module_index.json"
_SCAD_MODULE_INDEX_CACHE: dict[str, set[str]] | None = None
_METRIC_NUT_ISO4032 = {
    "m4": {"across_flats": 7.0, "thickness": 3.2, "hole_diameter": 4.3},
    "m5": {"across_flats": 8.0, "thickness": 4.0, "hole_diameter": 5.3},
    "m6": {"across_flats": 10.0, "thickness": 5.0, "hole_diameter": 6.4},
    "m8": {"across_flats": 13.0, "thickness": 6.5, "hole_diameter": 8.4},
    "m10": {"across_flats": 17.0, "thickness": 8.0, "hole_diameter": 10.5},
    "m12": {"across_flats": 19.0, "thickness": 10.0, "hole_diameter": 13.0},
}
_METRIC_BOLT_ISO4017 = {
    "m4": {"head_across_flats": 7.0, "head_height": 2.8, "shank_diameter": 4.0},
    "m5": {"head_across_flats": 8.0, "head_height": 3.5, "shank_diameter": 5.0},
    "m6": {"head_across_flats": 10.0, "head_height": 4.0, "shank_diameter": 6.0},
    "m8": {"head_across_flats": 13.0, "head_height": 5.3, "shank_diameter": 8.0},
    "m10": {"head_across_flats": 17.0, "head_height": 6.4, "shank_diameter": 10.0},
    "m12": {"head_across_flats": 19.0, "head_height": 7.5, "shank_diameter": 12.0},
}
_METRIC_WASHER_ISO7089 = {
    "m4": {"outer_diameter": 9.0, "inner_diameter": 4.3, "thickness": 0.8},
    "m5": {"outer_diameter": 10.0, "inner_diameter": 5.3, "thickness": 1.0},
    "m6": {"outer_diameter": 12.0, "inner_diameter": 6.4, "thickness": 1.6},
    "m8": {"outer_diameter": 16.0, "inner_diameter": 8.4, "thickness": 1.6},
    "m10": {"outer_diameter": 20.0, "inner_diameter": 10.5, "thickness": 2.0},
    "m12": {"outer_diameter": 24.0, "inner_diameter": 13.0, "thickness": 2.5},
}


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


def _load_scad_module_index_by_path() -> dict[str, set[str]]:
    global _SCAD_MODULE_INDEX_CACHE
    if _SCAD_MODULE_INDEX_CACHE is not None:
        return _SCAD_MODULE_INDEX_CACHE
    out: dict[str, set[str]] = {}
    if not _SCAD_INDEX_PATH.exists():
        _SCAD_MODULE_INDEX_CACHE = out
        return out
    try:
        payload = json.loads(_SCAD_INDEX_PATH.read_text(encoding="utf-8"))
        modules = payload.get("modules")
        if isinstance(modules, list):
            for item in modules:
                if not isinstance(item, dict):
                    continue
                path = str(item.get("path", "")).strip()
                module = str(item.get("module", "")).strip()
                if not path or not module:
                    continue
                out.setdefault(path.lower(), set()).add(module)
    except Exception:
        out = {}
    _SCAD_MODULE_INDEX_CACHE = out
    return out


def _resolve_library_path(lib: str, library_path: str) -> str:
    if library_path:
        return library_path.strip().replace("\\", "/").lower()
    aliases = {
        "mcad": "mcad/",
        "bosl2": "bosl2/",
    }
    return aliases.get(lib.strip().lower(), "")


def _normalize_library_call(params_raw: dict) -> dict:
    if not isinstance(params_raw, dict):
        raise ValueError("library_call requires params object.")
    module_name = str(params_raw.get("module", "")).strip()
    if not module_name:
        raise ValueError("library_call requires non-empty 'module'.")
    args = params_raw.get("args", {})
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ValueError("library_call 'args' must be an object of named parameters.")
    include_mode = str(params_raw.get("include_mode", "use")).strip().lower()
    if include_mode not in {"use", "include"}:
        raise ValueError("library_call include_mode must be 'use' or 'include'.")
    lib = str(params_raw.get("lib", "")).strip().lower()
    library_path = str(params_raw.get("library_path", "")).strip()
    library_paths_raw = params_raw.get("library_paths", None)
    if library_paths_raw is not None and not isinstance(library_paths_raw, list):
        raise ValueError("library_call 'library_paths' must be an array of strings.")

    # Resolve one-or-more library paths, or fall back to legacy lib/library_path.
    resolved_paths: list[str] = []
    if isinstance(library_paths_raw, list) and len(library_paths_raw) > 0:
        for item in library_paths_raw:
            p = str(item or "").strip()
            if p:
                resolved_paths.append(p.replace("\\", "/").lower())
    else:
        if not lib and not library_path:
            raise ValueError("library_call requires either 'library_paths', 'library_path' or 'lib'.")
        rp = _resolve_library_path(lib, library_path)
        if rp:
            resolved_paths.append(rp)

    # Validate module exists in our vendored index when possible.
    by_path = _load_scad_module_index_by_path()
    allowed: set[str] = set()
    for resolved_path in resolved_paths:
        if resolved_path.endswith("/"):
            for pth, mods in by_path.items():
                if pth.startswith(resolved_path):
                    allowed.update(mods)
        else:
            allowed.update(by_path.get(resolved_path, set()))
    if allowed and module_name not in allowed:
        examples = ", ".join(sorted(list(allowed))[:12])
        hint = resolved_paths[0] if resolved_paths else ""
        raise ValueError(
            f"library_call module '{module_name}' is not in index for '{hint}'. "
            f"Try one of: {examples}"
        )
    out = {
        "module": module_name,
        "args": args,
        "include_mode": include_mode,
    }
    if lib:
        out["lib"] = lib
    if library_path:
        out["library_path"] = library_path
    if resolved_paths and (isinstance(library_paths_raw, list) and len(library_paths_raw) > 0):
        # Keep multi-path form for downstream OpenSCAD include generation.
        out["library_paths"] = [p for p in (str(x).strip() for x in library_paths_raw) if p]
    return out


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
    if shape == "library_call":
        return shape, _normalize_library_call(params)
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
    elif shape == "spur_gear_pair":
        raw_t1 = params.get("teeth1", params.get("z1"))
        raw_t2 = params.get("teeth2", params.get("z2"))
        if raw_t1 is None or raw_t2 is None:
            raise ValueError("spur_gear_pair requires teeth1 and teeth2.")
        out_params["teeth1"] = _to_int_teeth(raw_t1, "teeth1")
        out_params["teeth2"] = _to_int_teeth(raw_t2, "teeth2")
        mod_key = params.get("module", params.get("pitch_module", params.get("m")))
        if mod_key is None:
            raise ValueError("spur_gear_pair requires module.")
        out_params["pitch_module"] = _to_pos_float(mod_key, "module", factor)
        fw = params.get("width", params.get("face_width", params.get("thickness")))
        if fw is None:
            raise ValueError("spur_gear_pair requires width.")
        out_params["face_width"] = _to_pos_float(fw, "width", factor)
        pa = params.get("pressure_angle", 20)
        out_params["pressure_angle"] = float(_to_pos_float(pa, "pressure_angle", 1.0))
    elif shape == "bearing_608":
        out_params["outer_diameter"] = 22.0
        out_params["inner_diameter"] = 8.0
        out_params["width"] = _to_pos_float(params.get("width", 7.0), "width", factor)
    elif shape == "bearing_6204":
        out_params["outer_diameter"] = 47.0
        out_params["inner_diameter"] = 20.0
        out_params["width"] = _to_pos_float(params.get("width", 14.0), "width", factor)
    elif shape == "hex_nut_iso4032":
        key = str(params.get("metric_size", params.get("size", "m8"))).strip().lower()
        preset = _METRIC_NUT_ISO4032.get(key)
        if preset:
            out_params["metric_size"] = key.upper()
            out_params["across_flats"] = float(preset["across_flats"])
            out_params["thickness"] = float(preset["thickness"])
            out_params["hole_diameter"] = float(preset["hole_diameter"])
        else:
            out_params["across_flats"] = _to_pos_float(params.get("across_flats"), "across_flats", factor)
            out_params["thickness"] = _to_pos_float(params.get("thickness"), "thickness", factor)
            out_params["hole_diameter"] = _to_pos_float(params.get("hole_diameter"), "hole_diameter", factor)
    elif shape == "hex_bolt_iso4017":
        key = str(params.get("metric_size", params.get("size", "m8"))).strip().lower()
        preset = _METRIC_BOLT_ISO4017.get(key)
        out_params["length"] = _to_pos_float(params.get("length"), "length", factor)
        if preset:
            out_params["metric_size"] = key.upper()
            out_params["head_across_flats"] = float(preset["head_across_flats"])
            out_params["head_height"] = float(preset["head_height"])
            out_params["shank_diameter"] = float(preset["shank_diameter"])
        else:
            out_params["head_across_flats"] = _to_pos_float(params.get("head_across_flats"), "head_across_flats", factor)
            out_params["head_height"] = _to_pos_float(params.get("head_height"), "head_height", factor)
            out_params["shank_diameter"] = _to_pos_float(params.get("shank_diameter"), "shank_diameter", factor)
    elif shape == "plain_washer_iso7089":
        key = str(params.get("metric_size", params.get("size", "m8"))).strip().lower()
        preset = _METRIC_WASHER_ISO7089.get(key)
        if preset:
            out_params["metric_size"] = key.upper()
            out_params["outer_diameter"] = float(preset["outer_diameter"])
            out_params["inner_diameter"] = float(preset["inner_diameter"])
            out_params["thickness"] = float(preset["thickness"])
        else:
            out_params["outer_diameter"] = _to_pos_float(params.get("outer_diameter"), "outer_diameter", factor)
            out_params["inner_diameter"] = _to_pos_float(params.get("inner_diameter"), "inner_diameter", factor)
            out_params["thickness"] = _to_pos_float(params.get("thickness"), "thickness", factor)
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
