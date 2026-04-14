from __future__ import annotations

# Central shape registry for DSL prompt + schema normalization.
# Add high-frequency business parts here to avoid editing multiple files.

CORE_SHAPES: tuple[str, ...] = (
    "sphere",
    "cylinder",
    "box",
    "shaft",
    "hollow_shaft",
    "stepped_shaft",
    "spur_gear",
    "regular_prism",
    "regular_pyramid",
)

SHAPE_ALIASES: dict[str, str] = {
    "prism": "regular_prism",
    "polygon_prism": "regular_prism",
    "pyramid": "regular_pyramid",
    "polygon_pyramid": "regular_pyramid",
    "solid_shaft": "shaft",
    "tube": "hollow_shaft",
    "sleeve": "hollow_shaft",
}

SHAPE_PARAM_LINES: tuple[str, ...] = (
    "- sphere: radius OR diameter",
    "- cylinder: radius OR diameter, and height",
    "- box: length, width, height",
    "- shaft (solid shaft): radius OR diameter, and length",
    "- hollow_shaft (tube/sleeve): outer_radius OR outer_diameter, inner_radius OR inner_diameter, and length",
    "- stepped_shaft (2-step shaft): radius1 OR diameter1, length1, radius2 OR diameter2, length2",
    "- spur_gear (standard involute spur, MCAD reference): teeth (integer tooth count), module (mm, pitch module m), width (mm, face width), pressure_angle (degrees, default 20)",
    "- regular_prism (right prism, regular n-gon base): sides (integer n>=3), radius (mm, circumradius of base), height (mm, prism length along extrusion)",
    "- regular_pyramid (right pyramid, regular n-gon base, apex centered above base): sides (integer n>=3), radius (mm, circumradius of base), height (mm, apex to base plane distance). Aliases: prism -> regular_prism, pyramid -> regular_pyramid.",
)

SHAPE_RULE_LINES: tuple[str, ...] = (
    '- For sphere/ball/球/球体 use shape="sphere".',
    '- For spur gear / 齿轮 / 直齿轮 / 齿数+模数 use shape="spur_gear" with teeth, module, width; pressure_angle optional (default 20).',
    '- For shaft / 轴 / 实心轴 use shape="shaft" with radius(or diameter), length.',
    '- For hollow shaft / 套筒 / 空心轴 / 管 use shape="hollow_shaft" with outer+inner radius(or diameter), length.',
    '- For stepped shaft / 台阶轴 / 阶梯轴 use shape="stepped_shaft" with radius1/length1 and radius2/length2.',
    '- For 棱柱 / 正n棱柱 / polygon prism use shape="regular_prism" with sides, radius, height.',
    '- For 棱锥 / 正n棱锥 / pyramid use shape="regular_pyramid" with sides, radius, height.',
)


def supported_shapes_set() -> frozenset[str]:
    return frozenset(CORE_SHAPES)


def build_shape_enum() -> str:
    return "|".join(CORE_SHAPES)


def build_shape_params_block() -> str:
    return "\n".join(SHAPE_PARAM_LINES)


def build_shape_rules_block() -> str:
    return "\n".join(SHAPE_RULE_LINES)
