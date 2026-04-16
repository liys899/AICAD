from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class RelationshipSpec:
    relations: list[str]
    source_text: str

    @property
    def has_constraints(self) -> bool:
        return len(self.relations) > 0


def parse_relationships_from_text(text: str) -> RelationshipSpec:
    t = (text or "").lower()
    rels: list[str] = []

    def _looks_like_interpart_coaxial(t0: str) -> bool:
        """
        Heuristic: only treat 'coaxial/同轴/共轴' as an inter-part relationship constraint
        when the user likely refers to alignment BETWEEN two+ parts.

        This avoids misclassifying single-part features like '同轴孔/同轴度/同轴线' as an
        assembly constraint (which would incorrectly require parts+ops).
        """
        if not any(k in t0 for k in ("同轴", "共轴", "coaxial", "same axis")):
            return False
        # Single-part feature cues (very common): coaxial holes / coaxiality tolerance / axis line.
        if any(k in t0 for k in ("同轴孔", "同轴度", "同轴线", "孔", "bore", "hole")):
            # If the text *also* strongly indicates multiple parts, allow relationship.
            pass
        # Multi-part / between-parts cues.
        multi_part_cues = (
            "与",
            "和",
            "以及",
            "之间",
            "两个",
            "两",
            "多",
            "零件",
            "部件",
            "组件",
            "装配",
            "assembly",
            "parts",
            "part",
            "between",
            "pair",
            "align",
            "aligned",
        )
        if any(k in t0 for k in multi_part_cues):
            return True
        # If no explicit multi-part cue, default to treating as single-part feature.
        return False

    # Spur gear meshing pair
    if any(k in t for k in ("啮合", "齿轮对", "一对齿轮", "gear pair", "mesh", "meshing")):
        rels.append("gear_mesh")
    # Coaxial / collinear axis
    if _looks_like_interpart_coaxial(t):
        rels.append("coaxial")
    # Through hole / drilling / piercing
    if any(k in t for k in ("穿孔", "通孔", "打孔", "钻孔", "through hole", "drill")):
        rels.append("through_hole")
    # Tangency
    if any(k in t for k in ("相切", "tangent", "tangency")):
        rels.append("tangent")

    # De-duplicate while keeping stable order
    out: list[str] = []
    for r in rels:
        if r not in out:
            out.append(r)
    return RelationshipSpec(relations=out, source_text=text or "")


def parse_relationships_from_messages(messages: list[dict[str, str]]) -> RelationshipSpec:
    # IMPORTANT:
    # Relationship constraints should reflect the user's *current* request.
    # If we merge the entire chat history, earlier keywords like "齿轮对/啮合/mesh"
    # can incorrectly force gear_mesh constraints on later unrelated single-part requests.
    #
    # Therefore we only consider the most recent non-empty user message.
    last_user_text = ""
    for m in reversed(messages or []):
        if (m.get("role") or "").strip().lower() != "user":
            continue
        c = m.get("content")
        if isinstance(c, str) and c.strip():
            last_user_text = c.strip()
            break
    return parse_relationships_from_text(last_user_text)


def build_relationship_guidance(spec: RelationshipSpec) -> str:
    if not spec.has_constraints:
        return ""
    lines = [
        "Relationship parser constraints (must satisfy in final DSL):",
    ]
    if "gear_mesh" in spec.relations:
        lines.extend(
            [
                "- gear_mesh: output an assembly with at least two spur_gear parts.",
                "- gear_mesh: include transform ops to position gears for meshing relationship.",
            ]
        )
    if "coaxial" in spec.relations:
        lines.append("- coaxial: parts sharing axis should be arranged with same x,y axis (z-offset allowed).")
    if "through_hole" in spec.relations:
        lines.append("- through_hole: use boolean difference op to create hole feature.")
    if "tangent" in spec.relations:
        lines.append("- tangent: place solids with explicit transform relations to represent tangency.")
    lines.append("Return ONE complete JSON object only.")
    return "\n".join(lines)
