from __future__ import annotations

from dsl_schema import NormalizedDsl
from relationship_parser import RelationshipSpec


_AXIAL_SHAPES = {
    "shaft",
    "hollow_shaft",
    "stepped_shaft",
    "cylinder",
    # Fasteners / ring-like parts are also axisymmetric and valid for coaxial constraints.
    "hex_bolt_iso4017",
    "hex_nut_iso4032",
    "plain_washer_iso7089",
    "bearing_608",
    "bearing_6204",
}


def _shape_count(parts: list[dict], shape: str) -> int:
    return sum(1 for p in parts if str(p.get("shape", "")).strip().lower() == shape)


def validate_relationship_consistency(dsl: NormalizedDsl, spec: RelationshipSpec) -> None:
    if not spec.has_constraints:
        return

    is_assembly = dsl.shape == "assembly"
    parts = dsl.parts or []
    ops = dsl.ops or []

    if "gear_mesh" in spec.relations:
        if not is_assembly:
            raise ValueError("Relationship gear_mesh requires assembly DSL with parts+ops.")
        if _shape_count(parts, "spur_gear") < 2:
            raise ValueError("Relationship gear_mesh requires at least two spur_gear parts.")
        if not any(op.get("type") == "transform" for op in ops):
            raise ValueError("Relationship gear_mesh requires transform ops to position gears.")

    if "coaxial" in spec.relations:
        if not is_assembly:
            raise ValueError("Relationship coaxial requires assembly DSL.")
        # Keep this constraint permissive: some LLM candidates may use generic part labels
        # (or alias-like shapes) before canonicalization. As long as there are >=2 parts and
        # explicit transforms, we can still encode coaxial placement robustly.
        if len(parts) < 2:
            raise ValueError(
                f"Relationship coaxial requires at least two parts (got {len(parts)}). "
                "If you intended a single-part feature like a coaxial hole, avoid specifying coaxial relationships."
            )
        # Coaxial implies explicit transform control in this DSL flavor.
        if not any(op.get("type") == "transform" for op in ops):
            raise ValueError("Relationship coaxial requires transform ops to align axes.")

    if "through_hole" in spec.relations:
        if not is_assembly:
            raise ValueError("Relationship through_hole requires assembly DSL.")
        if not any(op.get("type") == "boolean" and op.get("kind") == "difference" for op in ops):
            raise ValueError("Relationship through_hole requires boolean difference op.")

    if "tangent" in spec.relations:
        if not is_assembly:
            raise ValueError("Relationship tangent requires assembly DSL.")
        if len(parts) < 2:
            raise ValueError("Relationship tangent requires at least two parts.")
        if not any(op.get("type") == "transform" for op in ops):
            raise ValueError("Relationship tangent requires transform ops to encode placement.")
