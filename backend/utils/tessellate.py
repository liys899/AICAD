from ocp_tessellate.convert import to_assembly
try:
    from ocp_tessellate import PartGroup
except ImportError:
    # Newer ocp_tessellate exposes this type as OCP_PartGroup.
    from ocp_tessellate import OCP_PartGroup as PartGroup
from ocp_tessellate.convert import (
    tessellate_group,
    to_assembly,
)


def _is_ocp_binding(obj):
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return False
    mod = getattr(type(obj), "__module__", "") or ""
    return "OCP." in mod or "OCC." in mod


def _mesh_entry_from_instance(mesh):
    """Strip OCP objects from tessellation cache entry; keep arrays for JSON sanitize."""
    if not isinstance(mesh, dict):
        return mesh
    out = {k: v for k, v in mesh.items() if not _is_ocp_binding(v)}
    # three-cad-viewer renderShape expects these keys; avoid undefined.flat() in the viewer.
    for key in ("vertices", "normals", "triangles"):
        if key not in out or out[key] is None:
            out[key] = []
    if out.get("edges") is None:
        out["edges"] = []
    return out


def _inline_shape_refs(node, instances):
    """
    ocp_tessellate may leave shape: {'ref': n} on leaves; three-cad-viewer needs
    vertices/normals/triangles on shape.shape.
    """
    if not instances or not isinstance(node, dict):
        return
    parts = node.get("parts")
    # Only recurse into non-empty parts; empty list must not skip leaf shape inlining.
    if isinstance(parts, list) and parts:
        for p in parts:
            _inline_shape_refs(p, instances)
        return
    sh = node.get("shape")
    if not isinstance(sh, dict) or "vertices" in sh or "ref" not in sh:
        return
    ref = sh.get("ref")
    if not isinstance(ref, int) or ref < 0 or ref >= len(instances):
        return
    node["shape"] = _mesh_entry_from_instance(instances[ref])


def flatten_viewer_states(shapes_tree):
    """
    ocp_tessellate returns states as a tree; three-cad-viewer indexes flatly:
    states[shape.id] -> [mesh_visible, edge_visible]
    """
    flat = {}

    def walk(node):
        if not isinstance(node, dict):
            return
        parts = node.get("parts")
        if isinstance(parts, list) and parts:
            for p in parts:
                walk(p)
            return
        sid = node.get("id")
        st = node.get("state")
        if sid is not None and isinstance(st, (list, tuple)):
            flat[sid] = [int(st[0]), int(st[1])] if len(st) >= 2 else [int(st[0]), int(st[0])]

    walk(shapes_tree)
    return flat


def tessellate(
    *cad_objs, names=None, colors=None, alphas=None, progress=None, **kwargs
):
    global FIRST_CALL

    part_group = to_assembly(
        *cad_objs,
        names=names,
        colors=colors,
        alphas=alphas,
        progress=progress,
    )
    instances = None
    if isinstance(part_group, tuple):
        instances = part_group[1]
        part_group = part_group[0]

    if len(part_group.objects) == 1 and isinstance(
        part_group.objects[0], PartGroup
    ):
        part_group = part_group.objects[0]


    if instances is None:
        instances = []
    try:
        result = tessellate_group(part_group, instances)
    except TypeError:
        result = tessellate_group(part_group)

    if len(result) == 4:
        instances, shapes, states, _ = result
    else:
        instances, shapes, states = result

    _inline_shape_refs(shapes, instances)
    viewer_states = flatten_viewer_states(shapes)
    return shapes, viewer_states
