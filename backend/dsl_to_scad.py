from __future__ import annotations

from dsl_schema import NormalizedDsl


def dsl_to_scad(dsl: NormalizedDsl) -> tuple[str, list[dict]]:
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
