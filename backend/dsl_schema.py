from __future__ import annotations

from dataclasses import dataclass
import re


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

_SUPPORTED_SHAPES = frozenset({"sphere", "cylinder", "box"})
_NUM_WITH_UNIT_RE = re.compile(r"^\s*(?P<val>-?\d+(?:\.\d+)?)\s*(?P<unit>mm|cm|m|in|inch|inches|millimeter|millimeters|centimeter|centimeters|meter|meters)?\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class NormalizedDsl:
    version: str
    unit: str
    shape: str
    params: dict

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "unit": self.unit,
            "shape": self.shape,
            "params": self.params,
        }


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


def normalize_dsl(raw: dict) -> NormalizedDsl:
    if not isinstance(raw, dict):
        raise ValueError("DSL must be a JSON object.")

    shape = str(raw.get("shape", "")).strip().lower()
    if shape not in _SUPPORTED_SHAPES and "|" in shape:
        tokens = [x.strip() for x in shape.split("|") if x.strip()]
        for t in tokens:
            if t in _SUPPORTED_SHAPES:
                shape = t
                break
    if shape not in _SUPPORTED_SHAPES:
        raise ValueError(f"Unsupported shape '{shape}'. Allowed: {sorted(_SUPPORTED_SHAPES)}")

    unit = str(raw.get("unit", "mm")).strip().lower()
    if unit not in _UNIT_TO_MM and "|" in unit:
        # Model sometimes echoes schema enum text like "mm|cm|m|in".
        unit = "mm"
    if unit not in _UNIT_TO_MM:
        raise ValueError(f"Unsupported unit '{unit}'.")
    factor = _UNIT_TO_MM[unit]

    params = raw.get("params")
    if not isinstance(params, dict):
        raise ValueError("DSL 'params' must be an object.")

    out_params: dict[str, float] = {}
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

    return NormalizedDsl(
        version=str(raw.get("version", "1.0")),
        unit="mm",
        shape=shape,
        params=out_params,
    )
