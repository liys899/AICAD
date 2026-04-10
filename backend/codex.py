import ast
import importlib
import os
import re
import json
from openai import OpenAI
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

def _get_client() -> OpenAI:
    api_key = os.getenv("ZHIPU_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing environment variable ZHIPU_API_KEY. "
            "Set it in your environment or .env file."
        )
    return OpenAI(
        api_key=api_key,
        base_url=os.getenv("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/"),
    )


_NUM_UNIT_RE = re.compile(
    r"(?P<val>\d+(?:\.\d+)?)\s*(?P<unit>mm|millimeter(?:s)?|cm|centimeter(?:s)?|m|meter(?:s)?|in|inch(?:es)?)\b",
    re.IGNORECASE,
)


def _extract_hard_constraints(user_msg: str) -> str:
    """
    Extract simple numeric+unit constraints from the user's prompt.
    This is intentionally conservative: it's better to pass a short, accurate list
    than to hallucinate structure that isn't there.
    """
    if not user_msg:
        return ""
    hits = []
    for m in _NUM_UNIT_RE.finditer(user_msg):
        val = m.group("val")
        unit = m.group("unit").lower()
        # normalize unit variants
        unit = {
            "millimeter": "mm",
            "millimeters": "mm",
            "centimeter": "cm",
            "centimeters": "cm",
            "meter": "m",
            "meters": "m",
            "inch": "in",
            "inches": "in",
        }.get(unit, unit)
        hits.append(f"{val}{unit}")
    if not hits:
        return ""
    # de-dup while keeping order
    seen = set()
    uniq = []
    for h in hits:
        if h not in seen:
            seen.add(h)
            uniq.append(h)
    return ", ".join(uniq[:20])


def _strip_code_fences(text: str) -> str:
    if not text:
        return ""
    t = text.strip()
    # remove common markdown fences
    t = re.sub(r"^\s*```(?:python)?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*```\s*$", "", t)
    return t.strip()


def _validate_generated_module(obj_module):
    if not hasattr(obj_module, "obj"):
        raise ValueError("Generated code did not define variable 'obj'.")
    obj = getattr(obj_module, "obj")
    if obj is None:
        raise ValueError("Generated variable 'obj' is None.")
    # Strong guardrail: default to producing a 3D solid (not just a wire/edge/face).
    # Many "棒/棍子" prompts should be solids (cylinder/box). If a non-solid is returned,
    # treat it as invalid so the retry loop can steer the model.
    try:
        shape = obj.val() if hasattr(obj, "val") else obj
        st = getattr(shape, "ShapeType", None)
        st = st() if callable(st) else None
        if st and st not in ("Solid", "Compound", "Shell"):
            raise ValueError(f"Generated shape is not a 3D solid (ShapeType={st}).")
    except ValueError:
        raise
    except Exception:
        # If we can't introspect, don't fail here; execution already succeeded.
        pass
    return obj


_HISTORY_PREFIX = "# CQASK_HISTORY: "
_GENERATED_DIR = "generated"
_MAX_GENERATED_PY_FILES = 5


def _strip_leading_import_cq(code: str) -> str:
    """
    Model sometimes returns full file including 'import cadquery as cq'.
    Keep code body only; we add the import ourselves.
    """
    if not code:
        return ""
    lines = code.splitlines()
    i = 0
    # Drop any number of leading "import cadquery as cq" lines and adjacent blank lines.
    while i < len(lines):
        s = lines[i].strip()
        if s == "import cadquery as cq" or s == "":
            i += 1
            continue
        break
    return "\n".join(lines[i:]).strip()


def _build_forbidden_workplane_call_attrs() -> frozenset:
    """
    Names that are commonly hallucinated as cq.Workplane methods but do not exist
    in this environment's CadQuery. Built by probing getattr(wp, name) on a Workplane instance.
    """
    try:
        import cadquery as cq

        wp = cq.Workplane("XY")
        suspects = (
            "triangle",
            "cube",
            "square",
            "pyramid",
            "draw",
            "line_to",
            "make_box",
            "make_sphere",
            "fillet2d",
            "chamfer2d",
            "hole2d",
            "trapezoid",
            "hexagon",
            "pentagon",
            "octagon",
            "star",
            "donut",
            "torus",
        )
        return frozenset(s for s in suspects if getattr(wp, s, None) is None)
    except Exception:
        return frozenset(
            {
                "triangle",
                "cube",
                "square",
                "pyramid",
            }
        )


_FORBIDDEN_CQ_CALL_ATTRS = _build_forbidden_workplane_call_attrs()

# Always reject these names even if a future CadQuery build added similarly named helpers:
# models often hallucinate them and users expect strict compatibility with real APIs.
_ALWAYS_FORBIDDEN_CALL_ATTRS = frozenset({"triangle", "cube", "square"})

_MERGED_FORBIDDEN_CALL_ATTRS = _FORBIDDEN_CQ_CALL_ATTRS | _ALWAYS_FORBIDDEN_CALL_ATTRS

# Regex fallback: catches `.triangle(` even if AST parsing differs or code is odd.
_HALLUCINATED_METHOD_CALL_RE = re.compile(
    r"\.\s*(triangle|cube|square)\s*\(",
    re.IGNORECASE,
)

_ALLOWED_CQ_METHOD_NAMES_CACHE = None  # type: frozenset | None


def _get_allowed_cq_method_names() -> frozenset:
    """
    Union of callable names seen on cq module + typical cq.Workplane/CQ chain objects
    from the *installed* cadquery. Used to reject hallucinated method names before exec.
    """
    global _ALLOWED_CQ_METHOD_NAMES_CACHE
    if _ALLOWED_CQ_METHOD_NAMES_CACHE is not None:
        return _ALLOWED_CQ_METHOD_NAMES_CACHE
    import cadquery as cq

    names: set[str] = set()
    for n in dir(cq):
        if n.startswith("_"):
            continue
        try:
            o = getattr(cq, n, None)
            if callable(o) or isinstance(o, type):
                names.add(n)
        except Exception:
            pass
    for mod_name in ("exporters", "importers"):
        mod = getattr(cq, mod_name, None)
        if mod is None:
            continue
        for n in dir(mod):
            if n.startswith("_"):
                continue
            try:
                o = getattr(mod, n, None)
                if callable(o):
                    names.add(n)
            except Exception:
                pass

    wp = cq.Workplane("XY")
    protos: list = [wp]
    chain_builders = (
        lambda: wp.rect(1, 1),
        lambda: wp.circle(1),
        lambda: wp.rect(1, 1).extrude(1),
        lambda: wp.rect(1, 1).extrude(1).edges(),
        lambda: wp.rect(1, 1).extrude(1).faces(),
        lambda: wp.rect(1, 1).extrude(1).vertices(),
        lambda: wp.rect(1, 1).extrude(1).wire(),
        lambda: wp.rect(1, 1).extrude(1).solids(),
        lambda: wp.rect(1, 1).extrude(1).shells(),
    )
    for fn in chain_builders:
        try:
            protos.append(fn())
        except Exception:
            pass
    try:
        protos.append(wp.rect(1, 1).extrude(1).edges().fillet(0.1))
    except Exception:
        pass
    try:
        protos.append(wp.rect(1, 1).extrude(1).faces().chamfer(0.1))
    except Exception:
        pass

    for p in protos:
        for n in dir(p):
            if n.startswith("_"):
                continue
            try:
                if callable(getattr(p, n, None)):
                    names.add(n)
            except Exception:
                pass

    names -= _ALWAYS_FORBIDDEN_CALL_ATTRS
    _ALLOWED_CQ_METHOD_NAMES_CACHE = frozenset(names)
    return _ALLOWED_CQ_METHOD_NAMES_CACHE


def _collect_assignment_map(tree: ast.AST) -> dict:
    """Map simple Name -> value expr (last assignment wins)."""
    m: dict[str, ast.expr] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    m[t.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            m[node.target.id] = node.value
    return m


def _expr_is_cq_workplane_chain(
    expr: ast.expr | None, assignments: dict[str, ast.expr], depth: int = 0
) -> bool:
    """True if expr is cq.Workplane(...) or a chained call rooted on it, or a Name bound to such."""
    if depth > 64 or expr is None:
        return False
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute):
        fv = expr.func.value
        fa = expr.func.attr
        if isinstance(fv, ast.Name) and fv.id == "cq" and fa == "Workplane":
            return True
        if isinstance(fv, ast.Call):
            return _expr_is_cq_workplane_chain(fv, assignments, depth + 1)
    if isinstance(expr, ast.Name) and expr.id in assignments:
        return _expr_is_cq_workplane_chain(assignments[expr.id], assignments, depth + 1)
    return False


def _assert_no_forbidden_cq_calls(code: str) -> None:
    """
    Reject hallucinated CadQuery APIs before exec:
    - Regex for known fake names
    - For every call chain rooted at cq.Workplane(...), require the method name to exist
      on the installed cadquery (union of dir() probes).
    """
    if not code or not code.strip():
        raise ValueError("Empty generated code.")
    m = _HALLUCINATED_METHOD_CALL_RE.search(code)
    if m:
        name = m.group(1).lower()
        raise ValueError(
            f"Forbidden CadQuery call: .{name}() is not a valid cq.Workplane method here; "
            "use only documented APIs (e.g. polyline+close+extrude, rect, circle, box, extrude)."
        )
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise ValueError(f"Invalid Python syntax: {e}") from e

    try:
        allowed = _get_allowed_cq_method_names()
    except Exception as e:
        raise RuntimeError(
            "Cannot validate CadQuery API: cadquery must be importable. "
            f"Original error: {e}"
        ) from e

    assignments = _collect_assignment_map(tree)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        attr = node.func.attr
        recv = node.func.value

        if isinstance(recv, ast.Name) and recv.id == "cq" and attr == "Workplane":
            continue

        on_cq_chain = False
        if isinstance(recv, ast.Call) and _expr_is_cq_workplane_chain(recv, assignments):
            on_cq_chain = True
        elif isinstance(recv, ast.Name) and _expr_is_cq_workplane_chain(recv, assignments):
            on_cq_chain = True

        if not on_cq_chain:
            continue

        if attr in _MERGED_FORBIDDEN_CALL_ATTRS:
            raise ValueError(
                f"CadQuery has no .{attr}(); do not invent API calls. "
                "Use only methods present in your installed cadquery (e.g. polyline+close+extrude, rect, circle, box)."
            )
        if attr not in allowed:
            raise ValueError(
                f"CadQuery API check: .{attr}() is not a known callable on the cq.Workplane/CQ chain "
                f"for this installed cadquery. Use only real methods (validated against runtime dir())."
            )


_ALLOWED_IMPORT_PREFIXES = (
    "import cq_gears",
    "from cq_gears",
    "import parafoil",
    "from parafoil",
    "import cadquery as cq",
    "from cadquery import cq",  # unlikely but harmless
)


def _sanitize_model_code(code: str) -> str:
    """
    Strip disallowed imports and normalize common CadQuery API mistakes so the
    backend doesn't persist obviously-broken code as the "final" result.
    """
    body = _strip_leading_import_cq(code)
    if not body:
        return ""

    out_lines: list[str] = []
    _cq_import_line = re.compile(r"^\s*import\s+cadquery\s+as\s+cq\s*$", re.IGNORECASE)
    for line in body.splitlines():
        s = line.strip()
        # We always inject `import cadquery as cq`; drop any duplicate lines anywhere.
        if s == "import cadquery as cq" or _cq_import_line.match(line):
            continue
        if s.startswith("import ") or s.startswith("from "):
            # Only allow explicit cq_gears/parafoil imports; everything else must be avoided.
            if any(s.startswith(p) for p in _ALLOWED_IMPORT_PREFIXES):
                # Drop cadquery imports; we inject `import cadquery as cq` ourselves.
                if s.startswith("import cadquery") or s.startswith("from cadquery"):
                    continue
                out_lines.append(line)
            continue
        out_lines.append(line)

    normalized = "\n".join(out_lines).strip()
    # Normalize common wrong symbol: `workplane("XY")` -> `cq.Workplane("XY")`
    normalized = re.sub(r"\bworkplane\s*\(", "cq.Workplane(", normalized)
    # If model uses bare Workplane(...), prefer cq.Workplane(...)
    normalized = re.sub(r"(?<!cq\.)\bWorkplane\s*\(", "cq.Workplane(", normalized)
    return normalized.strip()


def _write_generated_state_by_id(id: str, history: list, code_body: str) -> str:
    if not os.path.exists(_GENERATED_DIR):
        os.makedirs(_GENERATED_DIR)
    file_path = os.path.join(_GENERATED_DIR, f"{id}.py")
    safe_history = history if isinstance(history, list) else []
    safe_history = [x for x in safe_history if isinstance(x, str)]
    body = _sanitize_model_code(code_body)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(_HISTORY_PREFIX + json.dumps(safe_history, ensure_ascii=False) + "\n")
        f.write(f"import cadquery as cq\n{body}\n")
    _cleanup_generated_py_files(_MAX_GENERATED_PY_FILES)
    return file_path


def _cleanup_generated_py_files(max_files: int = _MAX_GENERATED_PY_FILES) -> None:
    """
    Keep only the newest N python files in generated/.
    Older .py files are automatically removed.
    """
    if max_files <= 0 or not os.path.isdir(_GENERATED_DIR):
        return
    try:
        py_files = []
        for name in os.listdir(_GENERATED_DIR):
            if not name.lower().endswith(".py"):
                continue
            path = os.path.join(_GENERATED_DIR, name)
            if os.path.isfile(path):
                py_files.append(path)
        if len(py_files) <= max_files:
            return
        py_files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        for old_path in py_files[max_files:]:
            try:
                os.remove(old_path)
            except OSError:
                pass
    except OSError:
        pass


def generate_cq_obj(user_msg: str):
    client = _get_client()
    # Define the system message
    hard_constraints = _extract_hard_constraints(user_msg)
    system_msg = f"""
    You are a strict assistant that translates natural language into **Python CadQuery code**.
    Output **only raw Python code** (no Markdown, no backticks, no prose).
    VERY IMPORTANT:
    - The final result must be assigned to a variable named: obj
    - Do NOT use show_object, exporters, display, or any "show" functions
    - Do NOT read/write files, do NOT access network, do NOT use os/sys/subprocess
    - Use explicit dimensions when the user provides numbers; do not use random geometry
    - If the user specifies dimensions/units, they are **hard constraints** and must be satisfied exactly
    - Unless the user explicitly asks for 2D sketches/wires, the result must be a **3D solid** (e.g. cylinder/box/extrude)
    - When uncertain, choose the simplest valid solid that matches the request, rather than inventing extra features
    - **CadQuery API discipline (no hallucinations):** Only use real `cq.Workplane` / CQ methods. There is **NO** `triangle()`, `cube()`, or `square()` on `cq.Workplane`.
      For triangular shapes use `polyline` with three points, `.close()`, then `extrude`; use `rect`, `circle`, `box`, `extrude`, `fillet`, `chamfer` as documented.
    - The server validates cq.Workplane chains against the **installed** cadquery (runtime method list); do not invent method names.

    Common defaults:
    - For "一根棍子/棒": use a cylinder (circle + extrude) or a box, not a 2D wire.

    Hard constraints parsed from the user prompt (must respect if applicable): {hard_constraints or "None detected"}

    Here is the Cadquery API as a helpful resource:
 
    cq.Workplane.center(x, y)- Shift local coordinates to the specified location.
    cq.Workplane.lineTo(x, y[, forConstruction])- Make a line from the current point to the provided point
    cq.Workplane.line(xDist, yDist[, forConstruction])- Make a line from the current point to the provided point, using dimensions relative to the current point
    cq.Workplane.vLine(distance[, forConstruction])- Make a vertical line from the current point the provided distance
    cq.Workplane.vLineTo(yCoord[, forConstruction])- Make a vertical line from the current point to the provided y coordinate.
    cq.Workplane.hLine(distance[, forConstruction])- Make a horizontal line from the current point the provided distance
    cq.Workplane.hLineTo(xCoord[, forConstruction])- Make a horizontal line from the current point to the provided x coordinate.
    cq.Workplane.polarLine(distance, angle[, ...])- Make a line of the given length, at the given angle from the current point
    cq.Workplane.polarLineTo(distance, angle[, ...])- Make a line from the current point to the given polar coordinates
    cq.Workplane.moveTo([x, y])- Move to the specified point, without drawing.
    cq.Workplane.move([xDist, yDist])- Move the specified distance from the current point, without drawing.
    cq.Workplane.spline(listOfXYTuple[, tangents, ...])- Create a spline interpolated through the provided points (2D or 3D).
    cq.Workplane.parametricCurve(func[, N, start, ...])- Create a spline curve approximating the provided function.
    cq.Workplane.parametricSurface(func[, N, ...])- Create a spline surface approximating the provided function.
    cq.Workplane.threePointArc(point1, point2[, ...])- Draw an arc from the current point, through point1, and ending at point2
    cq.Workplane.sagittaArc(endPoint, sag[, ...])- Draw an arc from the current point to endPoint with an arc defined by the sag (sagitta).
    cq.Workplane.radiusArc(endPoint, radius[, ...])- Draw an arc from the current point to endPoint with an arc defined by the radius.
    cq.Workplane.tangentArcPoint(endpoint[, ...])- Draw an arc as a tangent from the end of the current edge to endpoint.
    cq.Workplane.mirrorY()- Mirror entities around the y axis of the workplane plane.
    cq.Workplane.mirrorX()- Mirror entities around the x axis of the workplane plane.
    cq.Workplane.wire([forConstruction])- Returns a CQ object with all pending edges connected into a wire.
    cq.Workplane.rect(xLen, yLen[, centered, ...])- Make a rectangle for each item on the stack.
    cq.Workplane.circle(radius[, forConstruction])- Make a circle for each item on the stack.
    cq.Workplane.ellipse(x_radius, y_radius[, ...])- Make an ellipse for each item on the stack.
    cq.Workplane.ellipseArc(x_radius, y_radius[, ...])- Draw an elliptical arc with x and y radiuses either with start point at current point or or current point being the center of the arc
    cq.Workplane.polyline(listOfXYTuple[, ...])- Create a polyline from a list of points
    cq.Workplane.close()- End construction, and attempt to build a closed wire.
    cq.Workplane.rarray(xSpacing, ySpacing, xCount, ...)- Creates an array of points and pushes them onto the stack.
    cq.Workplane.polarArray(radius, startAngle, ...)- Creates a polar array of points and pushes them onto the stack.
    cq.Workplane.slot2D(length, diameter[, angle])- Creates a rounded slot for each point on the stack.
    cq.Workplane.offset2D(d[, kind, forConstruction])- Creates a 2D offset wire.
    cq.Workplane.placeSketch(*sketches)- Place the provided sketch(es) based on the current items on the stack.
    cq.Workplane.gear(gear: BevelGear|CrossedHelicalGear|RackGear|RingGear|Worm)- Create a gear from the provided gear class.
    
    Here are also some gear classes from the library, use this as input to cq.Workplane.gear

    import cq_gears

    cq_gears.BevelGear(module, teeth_number, cone_angle, face_width, pressure_angle=20.0, helix_angle=0.0, clearance=0.0, backlash=0.0, bore_d)
    cq_gears.CrossedHelicalGear(module, teeth_number, width, pressure_angle=20.0, helix_angle=0.0, clearance=0.0, backlash=0.0, bore_d)
    cq_gears.RackGear(module, length, width, height, pressure_angle=20.0, helix_angle=0.0, clearance=0.0, backlash=0.0, bore_d)
    cq_gears.RingGear(module, teeth_number, width, rim_width, pressure_angle=20.0, helix_angle=0.0, clearance=0.0, backlash=0.0, bore_d)
    cq_gears.Worm(module, lead_angle, n_threads, length, pressure_angle=20.0, clearance=0.0, backlash=0.0, bore_d)
    cq_gears.SpurGear(self, module, teeth_number, width, pressure_angle=20.0, helix_angle=0.0, clearance=0.0, backlash=0.0, bore_d)
    
    Here is a way to generate airfoils with the coordinates being fed into cq.Workplane.polyline followed by a cq.Workplane.polyline.close

    For NACA airfoils use get_coords() for the following classes

    You MUST: import parafoil

    parafoil.CamberThicknessAirfoil(inlet_angle, outlet_angle, chord_length, angle_units="rad"|"deg")
    parafoil.NACAAirfoil(naca_string, chord_length)
    

    """
   
    model = os.getenv("ZHIPU_MODEL", "glm-4-flash")
    # Generate CadQuery code with validation + retry loop.
    # Many "货不对版" cases come from the model ignoring constraints; retries include
    # explicit failure feedback to steer it back.
    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]
    id = datetime.now().strftime("%Y-%m-%dT%H-%M-%S.%f")

    if not os.path.exists(_GENERATED_DIR):
        os.makedirs(_GENERATED_DIR)

    last_err = None
    code_content = ""
    for _attempt in range(3):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0,
        )
        code_content = _sanitize_model_code(_strip_code_fences(response.choices[0].message.content or ""))
        # Keep attempts separate, but finalize into generated/{id}.py on success.
        attempt_file = os.path.join(_GENERATED_DIR, f"{id}-attempt{_attempt+1}.py")
        try:
            _assert_no_forbidden_cq_calls(code_content)
            with open(attempt_file, "w", encoding="utf-8") as f:
                f.write(f"import cadquery as cq\n{code_content}\n")
            _cleanup_generated_py_files(_MAX_GENERATED_PY_FILES)
            spec = importlib.util.spec_from_file_location("obj_module", attempt_file)
            obj_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(obj_module)
            obj = _validate_generated_module(obj_module)
            _write_generated_state_by_id(id, [user_msg], code_content)
            return id, obj
        except Exception as e:
            last_err = e
            messages.append({"role": "assistant", "content": code_content})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "The previous code failed validation or execution.\n"
                        f"Error: {type(e).__name__}: {e}\n"
                        "Please output a corrected FULL Python CadQuery snippet that defines obj, "
                        "and strictly respects the user's hard constraints. "
                        "Do NOT invent CadQuery APIs (e.g. no triangle()/cube()/square() on Workplane; use polyline+close+extrude, rect, circle, box). "
                        "Output code only."
                    ),
                }
            )

    raise RuntimeError(f"Failed to generate valid CadQuery code after retries: {type(last_err).__name__}: {last_err}")
