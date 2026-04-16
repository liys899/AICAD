from __future__ import annotations

from pathlib import Path
from typing import Any

from dsl_schema import NormalizedDsl
from business_shapes import SHAPE_ALIASES

_LIB_PATH = Path(__file__).resolve().parent / "openscad_vendor" / "mcad" / "gears.scad"
_BOSL2_DIR = Path(__file__).resolve().parent / "openscad_vendor" / "BOSL2"
_MCAD_GEARS_SRC: str | None = None
_LIB_ALIAS_PATHS = {
    "mcad": "openscad_vendor/mcad/gears.scad",
    "bosl2": "openscad_vendor/BOSL2/std.scad",
    # Convenience aliases for threaded fastener modules.
    "bosl2_screws": "openscad_vendor/BOSL2/screws.scad",
    "bosl2_threading": "openscad_vendor/BOSL2/threading.scad",
}


def _inline_mcad_gears() -> str:
    """MCAD gears.scad (LGPL-2.1), vendored for self-contained SCAD + browser WASM."""
    global _MCAD_GEARS_SRC
    if _MCAD_GEARS_SRC is None:
        _MCAD_GEARS_SRC = _LIB_PATH.read_text(encoding="utf-8")
    return _MCAD_GEARS_SRC


def _inline_bosl2_bundle(entry_paths: list[str]) -> str:
    """
    Inline BOSL2 sources for openscad-wasm.

    openscad-wasm in the browser can't resolve include/use paths on disk, so for BOSL2 we
    paste the needed files into a single SCAD script and strip include/use directives.
    """
    seen: set[str] = set()
    chunks: list[str] = []

    def norm(p: str) -> str:
        return str(p).replace("\\", "/").strip()

    def resolve(include_target: str) -> Path | None:
        t = norm(include_target)
        if not t:
            return None
        # Most BOSL2 includes are like <structs.scad> relative to BOSL2 dir.
        if "/" not in t:
            return _BOSL2_DIR / t
        # If path already contains BOSL2/, resolve from vendor root.
        if t.lower().startswith("openscad_vendor/bosl2/"):
            return Path(__file__).resolve().parent / t
        # Otherwise treat as relative to BOSL2 dir.
        return _BOSL2_DIR / t

    def add_file(path: Path) -> None:
        try:
            p = path.resolve()
        except Exception:
            return
        if not str(p).lower().startswith(str(_BOSL2_DIR.resolve()).lower()):
            return
        key = str(p).replace("\\", "/").lower()
        if key in seen or not p.exists() or not p.is_file():
            return
        seen.add(key)
        text = p.read_text(encoding="utf-8", errors="ignore")
        # Extract include/use directives for recursive inlining.
        import re

        incs: list[str] = []
        out_lines: list[str] = []
        for line in text.splitlines():
            # OpenSCAD allows include/use with or without trailing semicolon.
            m = re.match(r"^\s*(include|use)\s*<([^>]+)>\s*;?\s*$", line)
            if m:
                incs.append(m.group(2))
                continue
            out_lines.append(line)
        # Inline dependencies first to preserve availability of symbols.
        for inc in incs:
            rp = resolve(inc)
            if rp is not None:
                add_file(rp)
        chunks.append(f"// --- BOSL2 inlined: {p.name} ---\n" + "\n".join(out_lines) + "\n")

    for ep in entry_paths:
        rp = resolve(ep)
        if rp is not None:
            add_file(rp)
    return "\n".join(chunks)


def _scad_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "undef"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, list):
        return "[" + ", ".join(_scad_literal(v) for v in value) + "]"
    raise ValueError(f"Unsupported OpenSCAD arg type: {type(value).__name__}")


def _scad_expr(value: Any) -> str:
    """Render value as OpenSCAD expression; bare strings are treated as identifiers/expressions."""
    if isinstance(value, str):
        return value
    return _scad_literal(value)


def _library_call_scad(params: dict) -> str:
    module = str(params.get("module", "")).strip()
    if not module:
        raise ValueError("library_call params.module is required.")
    include_mode = str(params.get("include_mode", "use")).strip().lower()
    if include_mode not in {"use", "include"}:
        raise ValueError("library_call include_mode must be use|include.")
    lib = str(params.get("lib", "")).strip().lower()
    # Support one or multiple library include paths.
    library_paths = params.get("library_paths")
    if library_paths is not None and not isinstance(library_paths, list):
        raise ValueError("library_call library_paths must be an array of strings.")
    resolved_paths: list[str] = []
    if isinstance(library_paths, list) and len(library_paths) > 0:
        for item in library_paths:
            p = str(item or "").strip()
            if p:
                resolved_paths.append(p)
    else:
        library_path = str(params.get("library_path", "")).strip()
        if not library_path:
            library_path = _LIB_ALIAS_PATHS.get(lib, "")
        if library_path:
            resolved_paths.append(library_path)
    if not resolved_paths:
        raise ValueError("library_call requires a valid library_path(s) or known lib alias.")
    args = params.get("args", {})
    if not isinstance(args, dict):
        raise ValueError("library_call args must be an object.")
    arg_items = [f"{k} = {_scad_literal(v)}" for k, v in args.items()]
    arg_str = ", ".join(arg_items)
    # BOSL2: inline sources so openscad-wasm can compile without filesystem includes.
    wants_bosl2 = any("/bosl2/" in str(p).replace("\\", "/").lower() for p in resolved_paths)
    if wants_bosl2:
        # Ensure std.scad is present so BOSL2 defines (_BOSL2_STD, dependencies) exist.
        entry = ["openscad_vendor/BOSL2/std.scad", *resolved_paths]
        lib_src = _inline_bosl2_bundle(entry)
        return "\n".join(
            [
                "// CQAsk: BOSL2 sources inlined for browser preview.",
                lib_src,
                f"{module}({arg_str});" if arg_str else f"{module}();",
            ]
        )

    return "\n".join([*[f"{include_mode} <{p}>;" for p in resolved_paths], f"{module}({arg_str});" if arg_str else f"{module}();"])


def _shape_body_scad(shape: str, p: dict, with_inlined_lib: bool = False) -> str:
    if shape == "library_call":
        return _library_call_scad(p)
    if shape == "sphere":
        return f"sphere(r={_scad_expr(p['radius'])}, $fn=96);"
    if shape == "cylinder":
        return f"cylinder(r={_scad_expr(p['radius'])}, h={_scad_expr(p['height'])}, $fn=96);"
    if shape == "shaft":
        return f"cylinder(r={_scad_expr(p['radius'])}, h={_scad_expr(p['length'])}, $fn=96);"
    if shape == "hollow_shaft":
        return "\n".join(
            [
                "difference() {",
                f"  cylinder(r={_scad_expr(p['outer_radius'])}, h={_scad_expr(p['length'])}, $fn=96);",
                f"  translate([0, 0, -0.01]) cylinder(r={_scad_expr(p['inner_radius'])}, h={_scad_expr(p['length'])} + 0.02, $fn=96);",
                "}",
            ]
        )
    if shape == "stepped_shaft":
        l1 = _scad_expr(p["length1"])
        l2 = _scad_expr(p["length2"])
        z1 = f"(-(({l1}) + ({l2})) / 2.0 + ({l1}) / 2.0)"
        z2 = f"((({l1}) + ({l2})) / 2.0 - ({l2}) / 2.0)"
        return "\n".join(
            [
                "union() {",
                f"  translate([0, 0, {z1}]) cylinder(r={_scad_expr(p['radius1'])}, h={l1}, center=true, $fn=96);",
                f"  translate([0, 0, {z2}]) cylinder(r={_scad_expr(p['radius2'])}, h={l2}, center=true, $fn=96);",
                "}",
            ]
        )
    if shape == "regular_prism":
        return (
            "linear_extrude(height = {height}, center = true, convexity = 10)\n"
            "  polygon([for (i = [0 : {sides} - 1]) [{radius} * cos(i * 360 / {sides}), {radius} * sin(i * 360 / {sides})]]);"
        ).format(height=_scad_expr(p["height"]), sides=_scad_expr(p["sides"]), radius=_scad_expr(p["radius"]))
    if shape == "regular_pyramid":
        n = _scad_expr(p["sides"])
        return "\n".join(
            [
                f"n = {n};",
                f"radius = {_scad_expr(p['radius'])};",
                f"height = {_scad_expr(p['height'])};",
                "pts = concat(",
                "  [for (i = [0 : n - 1]) [radius * cos(i * 360 / n), radius * sin(i * 360 / n), -height / 2]],",
                "  [[0, 0, height / 2]]",
                ");",
                "fcs = concat(",
                "  [[for (i = [n - 1 : -1 : 0]) i]],",
                "  [for (i = [0 : n - 1]) [i, (i + 1) % n, n]]",
                ");",
                "polyhedron(points = pts, faces = fcs, convexity = 10);",
            ]
        )
    if shape == "spur_gear":
        lines = []
        if with_inlined_lib:
            lines.extend(
                [
                    "// CQAsk: MCAD gears.scad inlined (LGPL-2.1) — involute spur reference.",
                    "",
                    _inline_mcad_gears(),
                    "",
                ]
            )
        lines.extend(
            [
                f"circular_pitch_mc = 180 * {_scad_expr(p['pitch_module'])};",
                "linear_extrude(height = {face_width}, center = true, convexity = 10)".format(face_width=_scad_expr(p["face_width"])),
                "  gear(number_of_teeth = {teeth}, circular_pitch = circular_pitch_mc, pressure_angle = {pa});".format(
                    teeth=_scad_expr(p["teeth"]),
                    pa=_scad_expr(p["pressure_angle"]),
                ),
            ]
        )
        return "\n".join(lines)
    if shape == "spur_gear_pair":
        t1 = _scad_expr(p["teeth1"])
        t2 = _scad_expr(p["teeth2"])
        m = _scad_expr(p["pitch_module"])
        b = _scad_expr(p["face_width"])
        pa = _scad_expr(p["pressure_angle"])
        center_dist = f"(({m}) * (({t1}) + ({t2})) / 2.0)"
        return "\n".join(
            [
                "union() {",
                "  // gear pair with theoretical center distance a = m*(z1+z2)/2",
                f"  translate([0, 0, 0]) linear_extrude(height = {b}, center = true, convexity = 10)",
                f"    gear(number_of_teeth = {t1}, circular_pitch = 180 * {m}, pressure_angle = {pa});",
                f"  translate([{center_dist}, 0, 0]) linear_extrude(height = {b}, center = true, convexity = 10)",
                f"    gear(number_of_teeth = {t2}, circular_pitch = 180 * {m}, pressure_angle = {pa});",
                "}",
            ]
        )
    if shape == "bearing_608" or shape == "bearing_6204":
        od_r = f"({_scad_expr(p['outer_diameter'])}) / 2.0"
        id_r = f"({_scad_expr(p['inner_diameter'])}) / 2.0"
        w = _scad_expr(p["width"])
        return "\n".join(
            [
                "difference() {",
                f"  cylinder(r={od_r}, h={w}, center=true, $fn=96);",
                f"  cylinder(r={id_r}, h=({w}) + 0.2, center=true, $fn=96);",
                "}",
            ]
        )
    if shape == "hex_nut_iso4032":
        af = _scad_expr(p["across_flats"])
        t = _scad_expr(p["thickness"])
        hole_r = f"({_scad_expr(p['hole_diameter'])}) / 2.0"
        circ_r = f"({af}) / 1.7320508075688772"
        return "\n".join(
            [
                "difference() {",
                f"  cylinder(h={t}, r={circ_r}, center=true, $fn=6);",
                f"  cylinder(h=({t}) + 0.2, r={hole_r}, center=true, $fn=64);",
                "}",
            ]
        )
    if shape == "hex_bolt_iso4017":
        af = _scad_expr(p["head_across_flats"])
        hh = _scad_expr(p["head_height"])
        sd = _scad_expr(p["shank_diameter"])
        l = _scad_expr(p["length"])
        circ_r = f"({af}) / 1.7320508075688772"
        sr = f"({sd}) / 2.0"
        return "\n".join(
            [
                "union() {",
                f"  translate([0,0,(({l}) - ({hh})) / 2.0]) cylinder(h={hh}, r={circ_r}, center=true, $fn=6);",
                f"  translate([0,0,-({hh}) / 2.0]) cylinder(h={l}, r={sr}, center=true, $fn=64);",
                "}",
            ]
        )
    if shape == "plain_washer_iso7089":
        od_r = f"({_scad_expr(p['outer_diameter'])}) / 2.0"
        id_r = f"({_scad_expr(p['inner_diameter'])}) / 2.0"
        t = _scad_expr(p["thickness"])
        return "\n".join(
            [
                "difference() {",
                f"  cylinder(h={t}, r={od_r}, center=true, $fn=96);",
                f"  cylinder(h=({t}) + 0.2, r={id_r}, center=true, $fn=64);",
                "}",
            ]
        )
    return "cube([{length}, {width}, {height}], center=true);".format(
        length=_scad_expr(p["length"]),
        width=_scad_expr(p["width"]),
        height=_scad_expr(p["height"]),
    )


def _shape_span_x(shape: str, p: dict) -> float:
    if shape == "sphere":
        return float(p["radius"]) * 2.0
    if shape == "cylinder":
        return float(p["radius"]) * 2.0
    if shape == "box":
        return float(p["length"])
    if shape == "shaft":
        return float(p["radius"]) * 2.0
    if shape == "hollow_shaft":
        return float(p["outer_radius"]) * 2.0
    if shape == "stepped_shaft":
        return max(float(p["radius1"]), float(p["radius2"])) * 2.0
    if shape == "regular_prism":
        return float(p["radius"]) * 2.0
    if shape == "regular_pyramid":
        return float(p["radius"]) * 2.0
    if shape == "spur_gear":
        # Approximate outer diameter d_a = m * (z + 2)
        return float(p["pitch_module"]) * (float(p["teeth"]) + 2.0)
    if shape == "spur_gear_pair":
        m = float(p["pitch_module"])
        z1 = float(p["teeth1"])
        z2 = float(p["teeth2"])
        return m * (z1 + z2) + 4.0
    if shape == "bearing_608" or shape == "bearing_6204":
        return float(p["outer_diameter"])
    if shape == "hex_nut_iso4032":
        return float(p["across_flats"]) * 1.2
    if shape == "hex_bolt_iso4017":
        return float(p["length"]) + float(p["head_across_flats"]) * 0.2
    if shape == "plain_washer_iso7089":
        return float(p["outer_diameter"])
    if shape == "library_call":
        return 30.0
    return 20.0


def _param_meta_for_assembly_value(name: str, label: str, value: float | int) -> dict:
    is_int = isinstance(value, int) and not isinstance(value, bool)
    base = float(value)
    if any(name.endswith(suffix) for suffix in ("_teeth", "_teeth1", "_teeth2", "_sides")):
        min_val = 3.0
        step = 1.0
    elif is_int:
        min_val = 1.0
        step = 1.0
    else:
        min_val = 0.1
        step = 0.1
    max_val = max(abs(base) * 3.0, base + 10.0, min_val + step * 20.0)
    return {"name": name, "label": label, "min": min_val, "max": max_val, "step": step, "value": base}


def _bind_assembly_params(parts: list[dict]) -> tuple[list[dict], list[str], list[dict]]:
    bound_parts: list[dict] = []
    decl_lines: list[str] = []
    params_meta: list[dict] = []
    for idx, part in enumerate(parts):
        shape = str(part.get("shape", ""))
        raw_params = part.get("params", {}) if isinstance(part.get("params"), dict) else {}
        out_params: dict[str, Any] = {}
        for key, value in raw_params.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                var_name = f"p{idx}_{key}"
                out_params[key] = var_name
                decl_lines.append(f"{var_name} = {value};")
                params_meta.append(_param_meta_for_assembly_value(var_name, f"P{idx} {shape} {key}", value))
            else:
                out_params[key] = value
        bound_parts.append({"shape": shape, "params": out_params})
    return bound_parts, decl_lines, params_meta


def _render_assembly_with_ops(parts: list[dict], ops: list[dict], result_ref: str | None) -> tuple[str, list[dict]]:
    op_map = {op["name"]: op for op in ops}
    shape_to_part_refs: dict[str, list[str]] = {}
    for i, part in enumerate(parts):
        shape = str(part.get("shape", "")).strip().lower()
        if not shape:
            continue
        shape_to_part_refs.setdefault(shape, []).append(f"p{i}")

    def _resolve_part_ref(ref: str) -> str | None:
        token = ref.strip()
        if not token:
            return None
        low = token.lower()
        if low.startswith("p") and low[1:].isdigit():
            idx = int(low[1:])
            if 0 <= idx < len(parts):
                return f"p{idx}"
            return None
        if low.startswith("part_") and low[5:].isdigit():
            idx = int(low[5:])
            if 0 <= idx < len(parts):
                return f"p{idx}"
            return None
        if low.startswith("part") and low[4:].isdigit():
            idx = int(low[4:])
            if 0 <= idx < len(parts):
                return f"p{idx}"
            return None
        if low.isdigit():
            idx = int(low)
            if 0 <= idx < len(parts):
                return f"p{idx}"
            return None
        # Compatibility: allow referencing part by shape name when unique.
        canonical = SHAPE_ALIASES.get(low, low)
        matches = shape_to_part_refs.get(canonical, [])
        if len(matches) == 1:
            return matches[0]
        return None

    def _render_ref(ref: str, indent: int = 0) -> list[str]:
        pad = " " * indent
        part_ref = _resolve_part_ref(ref)
        if part_ref is not None:
            idx = int(part_ref[1:])
            if idx < 0 or idx >= len(parts):
                raise ValueError(f"Unknown part ref '{ref}'.")
            return [f"{pad}part_{idx}();"]
        op = op_map.get(ref)
        if not op:
            raise ValueError(f"Unknown op ref '{ref}'.")
        if op["type"] == "transform":
            tx, ty, tz = op["translate"]
            rx, ry, rz = op["rotate"]
            lines = [
                f"{pad}translate([{tx}, {ty}, {tz}])",
                f"{pad}rotate([{rx}, {ry}, {rz}]) {{",
            ]
            lines.extend(_render_ref(op["target"], indent + 2))
            lines.append(f"{pad}}}")
            return lines
        lines = [f"{pad}{op['kind']}() {{"]
        for target in op["targets"]:
            lines.extend(_render_ref(target, indent + 2))
        lines.append(f"{pad}}}")
        return lines

    bound_parts, decl_lines, params_meta = _bind_assembly_params(parts)
    lines: list[str] = []
    has_gear = any(part.get("shape") == "spur_gear" for part in parts)
    if has_gear:
        lines.extend(
            [
                "// CQAsk: MCAD gears.scad inlined (LGPL-2.1) — involute spur reference.",
                "",
                _inline_mcad_gears(),
                "",
            ]
        )
    if decl_lines:
        lines.extend(decl_lines)
        lines.append("")
    for idx, part in enumerate(bound_parts):
        lines.append(f"module part_{idx}() {{")
        body = _shape_body_scad(part["shape"], part["params"]).splitlines()
        lines.extend([f"  {ln}" for ln in body])
        lines.append("}")
        lines.append("")
    final_ref = result_ref or ops[-1]["name"]
    lines.extend(_render_ref(final_ref))
    lines.append("")
    return "\n".join(lines), params_meta


def dsl_to_scad(dsl: NormalizedDsl) -> tuple[str, list[dict]]:
    if dsl.shape == "assembly":
        parts = dsl.parts or []
        if not parts:
            raise ValueError("assembly requires non-empty 'parts'.")
        ops = dsl.ops or []
        if ops:
            return _render_assembly_with_ops(parts, ops, dsl.result)
        bound_parts, decl_lines, params_meta = _bind_assembly_params(parts)
        has_gear = any(part.get("shape") == "spur_gear" for part in parts)
        lines: list[str] = []
        if has_gear:
            lines.extend(
                [
                    "// CQAsk: MCAD gears.scad inlined (LGPL-2.1) — involute spur reference.",
                    "",
                    _inline_mcad_gears(),
                    "",
                ]
            )
        if decl_lines:
            lines.extend(decl_lines)
            lines.append("")
        lines.append("union() {")
        cursor_x = 0.0
        gap = 2.0
        for idx, part in enumerate(bound_parts):
            span_x = max(0.1, _shape_span_x(part["shape"], part["params"]))
            center_x = cursor_x + span_x / 2.0
            lines.append(f"  // part[{idx}] {part['shape']}")
            lines.append(f"  translate([{center_x:.4f}, 0, 0]) {{")
            part_body = _shape_body_scad(part["shape"], part["params"]).splitlines()
            lines.extend([f"    {ln}" for ln in part_body])
            lines.append("  }")
            cursor_x += span_x + gap
        lines.append("}")
        lines.append("")
        return "\n".join(lines), params_meta

    p = dsl.params
    if dsl.shape == "sphere":
        script = "\n".join(
            [
                f"radius = {p['radius']};",
                "sphere(r=radius, $fn=96);",
            ]
        )
        return script, [{"name": "radius", "label": "Radius (mm)", "min": 0.1, "max": max(200.0, p["radius"] * 3), "step": 0.1, "value": p["radius"]}]

    if dsl.shape == "cylinder":
        script = "\n".join(
            [
                f"radius = {p['radius']};",
                f"height = {p['height']};",
                "cylinder(r=radius, h=height, $fn=96);",
            ]
        )
        return script, [
            {"name": "radius", "label": "Radius (mm)", "min": 0.1, "max": max(200.0, p["radius"] * 3), "step": 0.1, "value": p["radius"]},
            {"name": "height", "label": "Height (mm)", "min": 0.1, "max": max(400.0, p["height"] * 3), "step": 0.1, "value": p["height"]},
        ]

    if dsl.shape == "shaft":
        script = "\n".join(
            [
                f"radius = {p['radius']};",
                f"length = {p['length']};",
                "cylinder(r=radius, h=length, $fn=96);",
            ]
        )
        return script, [
            {"name": "radius", "label": "Shaft Radius (mm)", "min": 0.1, "max": max(200.0, p["radius"] * 3), "step": 0.1, "value": p["radius"]},
            {"name": "length", "label": "Shaft Length (mm)", "min": 0.1, "max": max(500.0, p["length"] * 3), "step": 0.1, "value": p["length"]},
        ]

    if dsl.shape == "hollow_shaft":
        script = "\n".join(
            [
                f"outer_radius = {p['outer_radius']};",
                f"inner_radius = {p['inner_radius']};",
                f"length = {p['length']};",
                "difference() {",
                "  cylinder(r=outer_radius, h=length, $fn=96);",
                "  translate([0, 0, -0.01]) cylinder(r=inner_radius, h=length + 0.02, $fn=96);",
                "}",
            ]
        )
        return script, [
            {"name": "outer_radius", "label": "Outer Radius (mm)", "min": 0.2, "max": max(200.0, p["outer_radius"] * 3), "step": 0.1, "value": p["outer_radius"]},
            {"name": "inner_radius", "label": "Inner Radius (mm)", "min": 0.1, "max": max(100.0, p["inner_radius"] * 3), "step": 0.1, "value": p["inner_radius"]},
            {"name": "length", "label": "Shaft Length (mm)", "min": 0.1, "max": max(500.0, p["length"] * 3), "step": 0.1, "value": p["length"]},
        ]

    if dsl.shape == "stepped_shaft":
        l1 = float(p["length1"])
        l2 = float(p["length2"])
        z1 = -(l1 + l2) / 2.0 + l1 / 2.0
        z2 = (l1 + l2) / 2.0 - l2 / 2.0
        script = "\n".join(
            [
                f"radius1 = {p['radius1']};",
                f"length1 = {p['length1']};",
                f"radius2 = {p['radius2']};",
                f"length2 = {p['length2']};",
                "total_len = length1 + length2;",
                "union() {",
                f"  translate([0, 0, {z1}]) cylinder(r=radius1, h=length1, center=true, $fn=96);",
                f"  translate([0, 0, {z2}]) cylinder(r=radius2, h=length2, center=true, $fn=96);",
                "}",
            ]
        )
        return script, [
            {"name": "radius1", "label": "Step1 Radius (mm)", "min": 0.1, "max": max(200.0, p["radius1"] * 3), "step": 0.1, "value": p["radius1"]},
            {"name": "length1", "label": "Step1 Length (mm)", "min": 0.1, "max": max(300.0, p["length1"] * 3), "step": 0.1, "value": p["length1"]},
            {"name": "radius2", "label": "Step2 Radius (mm)", "min": 0.1, "max": max(200.0, p["radius2"] * 3), "step": 0.1, "value": p["radius2"]},
            {"name": "length2", "label": "Step2 Length (mm)", "min": 0.1, "max": max(300.0, p["length2"] * 3), "step": 0.1, "value": p["length2"]},
        ]

    if dsl.shape == "spur_gear":
        teeth = int(p["teeth"])
        pitch_module = float(p["pitch_module"])
        face_width = float(p["face_width"])
        pressure_angle = float(p["pressure_angle"])
        lib = _inline_mcad_gears()
        body = "\n".join(
            [
                "// CQAsk: MCAD gears.scad inlined (LGPL-2.1) — involute spur reference.",
                "",
                lib,
                "",
                f"teeth = {teeth};",
                f"pitch_module = {pitch_module};",
                f"face_width = {face_width};",
                f"pressure_angle = {pressure_angle};",
                "circular_pitch_mc = 180 * pitch_module;",
                "",
                "linear_extrude(height = face_width, center = true, convexity = 10)",
                "  gear(number_of_teeth = teeth, circular_pitch = circular_pitch_mc, pressure_angle = pressure_angle);",
                "",
            ]
        )
        meta = [
            {"name": "teeth", "label": "齿数 z", "min": 3, "max": max(128, teeth + 40), "step": 1, "value": float(teeth)},
            {"name": "pitch_module", "label": "模数 m (mm)", "min": 0.2, "max": max(10.0, pitch_module * 3), "step": 0.1, "value": pitch_module},
            {"name": "face_width", "label": "齿宽 (mm)", "min": 0.5, "max": max(80.0, face_width * 3), "step": 0.1, "value": face_width},
            {"name": "pressure_angle", "label": "压力角 (°)", "min": 14.0, "max": 30.0, "step": 0.5, "value": pressure_angle},
        ]
        return body, meta

    if dsl.shape == "spur_gear_pair":
        t1 = int(p["teeth1"])
        t2 = int(p["teeth2"])
        m = float(p["pitch_module"])
        b = float(p["face_width"])
        pa = float(p["pressure_angle"])
        lib = _inline_mcad_gears()
        center_dist = m * (t1 + t2) / 2.0
        body = "\n".join(
            [
                "// CQAsk: MCAD gears.scad inlined (LGPL-2.1) — involute spur reference.",
                "",
                lib,
                "",
                f"teeth1 = {t1};",
                f"teeth2 = {t2};",
                f"pitch_module = {m};",
                f"face_width = {b};",
                f"pressure_angle = {pa};",
                "circular_pitch_mc = 180 * pitch_module;",
                "center_dist = pitch_module * (teeth1 + teeth2) / 2;",
                "union() {",
                "  translate([0,0,0]) linear_extrude(height = face_width, center = true, convexity = 10)",
                "    gear(number_of_teeth = teeth1, circular_pitch = circular_pitch_mc, pressure_angle = pressure_angle);",
                "  translate([center_dist,0,0]) linear_extrude(height = face_width, center = true, convexity = 10)",
                "    gear(number_of_teeth = teeth2, circular_pitch = circular_pitch_mc, pressure_angle = pressure_angle);",
                "}",
                "",
            ]
        )
        return body, [
            {"name": "teeth1", "label": "主动轮齿数 z1", "min": 3, "max": max(128, t1 + 40), "step": 1, "value": float(t1)},
            {"name": "teeth2", "label": "从动轮齿数 z2", "min": 3, "max": max(128, t2 + 40), "step": 1, "value": float(t2)},
            {"name": "pitch_module", "label": "模数 m (mm)", "min": 0.2, "max": max(10.0, m * 3), "step": 0.1, "value": m},
            {"name": "face_width", "label": "齿宽 (mm)", "min": 0.5, "max": max(80.0, b * 3), "step": 0.1, "value": b},
        ]

    if dsl.shape == "bearing_608" or dsl.shape == "bearing_6204":
        od = float(p["outer_diameter"])
        id_ = float(p["inner_diameter"])
        w = float(p["width"])
        script = "\n".join(
            [
                f"outer_diameter = {od};",
                f"inner_diameter = {id_};",
                f"width = {w};",
                "difference() {",
                "  cylinder(r=outer_diameter/2, h=width, center=true, $fn=96);",
                "  cylinder(r=inner_diameter/2, h=width + 0.2, center=true, $fn=64);",
                "}",
            ]
        )
        return script, [{"name": "width", "label": "轴承宽度 (mm)", "min": 1.0, "max": max(40.0, w * 3), "step": 0.1, "value": w}]

    if dsl.shape == "hex_nut_iso4032":
        af = float(p["across_flats"])
        t = float(p["thickness"])
        hd = float(p["hole_diameter"])
        script = "\n".join(
            [
                f"across_flats = {af};",
                f"thickness = {t};",
                f"hole_diameter = {hd};",
                "circ_r = across_flats / 1.7320508075688772;",
                "difference() {",
                "  cylinder(h=thickness, r=circ_r, center=true, $fn=6);",
                "  cylinder(h=thickness + 0.2, r=hole_diameter/2, center=true, $fn=64);",
                "}",
            ]
        )
        return script, []

    if dsl.shape == "hex_bolt_iso4017":
        af = float(p["head_across_flats"])
        hh = float(p["head_height"])
        sd = float(p["shank_diameter"])
        l = float(p["length"])
        script = "\n".join(
            [
                f"head_across_flats = {af};",
                f"head_height = {hh};",
                f"shank_diameter = {sd};",
                f"length = {l};",
                "circ_r = head_across_flats / 1.7320508075688772;",
                "union() {",
                "  translate([0,0,(length - head_height)/2]) cylinder(h=head_height, r=circ_r, center=true, $fn=6);",
                "  translate([0,0,-head_height/2]) cylinder(h=length, r=shank_diameter/2, center=true, $fn=64);",
                "}",
            ]
        )
        return script, [{"name": "length", "label": "螺栓长度 (mm)", "min": 4.0, "max": max(120.0, l * 3), "step": 0.5, "value": l}]

    if dsl.shape == "plain_washer_iso7089":
        od = float(p["outer_diameter"])
        id_ = float(p["inner_diameter"])
        t = float(p["thickness"])
        script = "\n".join(
            [
                f"outer_diameter = {od};",
                f"inner_diameter = {id_};",
                f"thickness = {t};",
                "difference() {",
                "  cylinder(h=thickness, r=outer_diameter/2, center=true, $fn=96);",
                "  cylinder(h=thickness + 0.2, r=inner_diameter/2, center=true, $fn=64);",
                "}",
            ]
        )
        return script, []

    if dsl.shape == "regular_prism":
        sides = int(p["sides"])
        radius = float(p["radius"])
        height = float(p["height"])
        script = "\n".join(
            [
                f"sides = {sides};",
                f"radius = {radius};",
                f"height = {height};",
                "linear_extrude(height = height, center = true, convexity = 10)",
                "  polygon([for (i = [0 : sides - 1]) [radius * cos(i * 360 / sides), radius * sin(i * 360 / sides)]]);",
                "",
            ]
        )
        return script, [
            {"name": "sides", "label": "底面边数 n", "min": 3, "max": 64, "step": 1, "value": float(sides)},
            {"name": "radius", "label": "外接圆半径 (mm)", "min": 0.1, "max": max(200.0, radius * 3), "step": 0.1, "value": radius},
            {"name": "height", "label": "棱柱高度 (mm)", "min": 0.1, "max": max(400.0, height * 3), "step": 0.1, "value": height},
        ]

    if dsl.shape == "regular_pyramid":
        sides = int(p["sides"])
        radius = float(p["radius"])
        height = float(p["height"])
        script = "\n".join(
            [
                f"sides = {sides};",
                f"radius = {radius};",
                f"height = {height};",
                "n = sides;",
                "pts = concat(",
                "  [for (i = [0 : n - 1]) [radius * cos(i * 360 / n), radius * sin(i * 360 / n), -height / 2]],",
                "  [[0, 0, height / 2]]",
                ");",
                "fcs = concat(",
                "  [[for (i = [n - 1 : -1 : 0]) i]],",
                "  [for (i = [0 : n - 1]) [i, (i + 1) % n, n]]",
                ");",
                "polyhedron(points = pts, faces = fcs, convexity = 10);",
                "",
            ]
        )
        return script, [
            {"name": "sides", "label": "底面边数 n", "min": 3, "max": 64, "step": 1, "value": float(sides)},
            {"name": "radius", "label": "底面外接圆半径 (mm)", "min": 0.1, "max": max(200.0, radius * 3), "step": 0.1, "value": radius},
            {"name": "height", "label": "锥高 (mm)", "min": 0.1, "max": max(400.0, height * 3), "step": 0.1, "value": height},
        ]

    if dsl.shape == "library_call":
        return _library_call_scad(p), []

    script = "\n".join(
        [
            f"length = {p['length']};",
            f"width = {p['width']};",
            f"height = {p['height']};",
            "cube([length, width, height], center=true);",
        ]
    )
    return script, [
        {"name": "length", "label": "Length (mm)", "min": 0.1, "max": max(400.0, p["length"] * 3), "step": 0.1, "value": p["length"]},
        {"name": "width", "label": "Width (mm)", "min": 0.1, "max": max(400.0, p["width"] * 3), "step": 0.1, "value": p["width"]},
        {"name": "height", "label": "Height (mm)", "min": 0.1, "max": max(400.0, p["height"] * 3), "step": 0.1, "value": p["height"]},
    ]
