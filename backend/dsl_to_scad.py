from __future__ import annotations

from pathlib import Path

from dsl_schema import NormalizedDsl

_LIB_PATH = Path(__file__).resolve().parent / "openscad_vendor" / "mcad" / "gears.scad"
_MCAD_GEARS_SRC: str | None = None


def _inline_mcad_gears() -> str:
    """MCAD gears.scad (LGPL-2.1), vendored for self-contained SCAD + browser WASM."""
    global _MCAD_GEARS_SRC
    if _MCAD_GEARS_SRC is None:
        _MCAD_GEARS_SRC = _LIB_PATH.read_text(encoding="utf-8")
    return _MCAD_GEARS_SRC


def _shape_body_scad(shape: str, p: dict, with_inlined_lib: bool = False) -> str:
    if shape == "sphere":
        return f"sphere(r={p['radius']}, $fn=96);"
    if shape == "cylinder":
        return f"cylinder(r={p['radius']}, h={p['height']}, $fn=96);"
    if shape == "shaft":
        return f"cylinder(r={p['radius']}, h={p['length']}, $fn=96);"
    if shape == "hollow_shaft":
        return "\n".join(
            [
                "difference() {",
                f"  cylinder(r={p['outer_radius']}, h={p['length']}, $fn=96);",
                f"  translate([0, 0, -0.01]) cylinder(r={p['inner_radius']}, h={p['length']} + 0.02, $fn=96);",
                "}",
            ]
        )
    if shape == "stepped_shaft":
        l1 = float(p["length1"])
        l2 = float(p["length2"])
        z1 = -(l1 + l2) / 2.0 + l1 / 2.0
        z2 = (l1 + l2) / 2.0 - l2 / 2.0
        return "\n".join(
            [
                "union() {",
                f"  translate([0, 0, {z1}]) cylinder(r={p['radius1']}, h={l1}, center=true, $fn=96);",
                f"  translate([0, 0, {z2}]) cylinder(r={p['radius2']}, h={l2}, center=true, $fn=96);",
                "}",
            ]
        )
    if shape == "regular_prism":
        return (
            "linear_extrude(height = {height}, center = true, convexity = 10)\n"
            "  polygon([for (i = [0 : {sides} - 1]) [{radius} * cos(i * 360 / {sides}), {radius} * sin(i * 360 / {sides})]]);"
        ).format(height=p["height"], sides=int(p["sides"]), radius=p["radius"])
    if shape == "regular_pyramid":
        n = int(p["sides"])
        return "\n".join(
            [
                f"n = {n};",
                f"radius = {p['radius']};",
                f"height = {p['height']};",
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
                f"circular_pitch_mc = 180 * {float(p['pitch_module'])};",
                "linear_extrude(height = {face_width}, center = true, convexity = 10)".format(
                    face_width=float(p["face_width"])
                ),
                "  gear(number_of_teeth = {teeth}, circular_pitch = circular_pitch_mc, pressure_angle = {pa});".format(
                    teeth=int(p["teeth"]),
                    pa=float(p["pressure_angle"]),
                ),
            ]
        )
        return "\n".join(lines)
    return "cube([{length}, {width}, {height}], center=true);".format(
        length=p["length"],
        width=p["width"],
        height=p["height"],
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
    return 20.0


def _render_assembly_with_ops(parts: list[dict], ops: list[dict], result_ref: str | None) -> str:
    op_map = {op["name"]: op for op in ops}

    def _render_ref(ref: str, indent: int = 0) -> list[str]:
        pad = " " * indent
        if ref.startswith("p") and ref[1:].isdigit():
            idx = int(ref[1:])
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
    for idx, part in enumerate(parts):
        lines.append(f"module part_{idx}() {{")
        body = _shape_body_scad(part["shape"], part["params"]).splitlines()
        lines.extend([f"  {ln}" for ln in body])
        lines.append("}")
        lines.append("")
    final_ref = result_ref or ops[-1]["name"]
    lines.extend(_render_ref(final_ref))
    lines.append("")
    return "\n".join(lines)


def dsl_to_scad(dsl: NormalizedDsl) -> tuple[str, list[dict]]:
    if dsl.shape == "assembly":
        parts = dsl.parts or []
        if not parts:
            raise ValueError("assembly requires non-empty 'parts'.")
        ops = dsl.ops or []
        if ops:
            return _render_assembly_with_ops(parts, ops, dsl.result), []
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
        lines.append("union() {")
        cursor_x = 0.0
        gap = 2.0
        for idx, part in enumerate(parts):
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
        return "\n".join(lines), []

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
