import os
import shutil
import subprocess


def _resolve_openscad_bin() -> str | None:
    # 1) explicit env override
    env_bin = (os.getenv("OPENSCAD_BIN") or "").strip()
    if env_bin and os.path.isfile(env_bin):
        return env_bin

    # 2) search common command names in PATH
    for cmd in ("openscad", "openscad.com", "openscad.exe"):
        p = shutil.which(cmd)
        if p:
            return p

    # 3) common Windows install locations
    candidates = [
        r"C:\Program Files\OpenSCAD\openscad.com",
        r"C:\Program Files\OpenSCAD\openscad.exe",
        r"C:\Program Files (x86)\OpenSCAD\openscad.com",
        r"C:\Program Files (x86)\OpenSCAD\openscad.exe",
    ]
    local_app = os.getenv("LOCALAPPDATA")
    if local_app:
        candidates.extend(
            [
                os.path.join(local_app, "Programs", "OpenSCAD", "openscad.com"),
                os.path.join(local_app, "Programs", "OpenSCAD", "openscad.exe"),
            ]
        )
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def get_donwload_string(id: str, extension: str = "step"):
    scad_path = f"generated_scad/{id}.scad"
    if not os.path.exists(scad_path):
        raise FileNotFoundError(f"SCAD source not found for id={id}")

    extension = (extension or "scad").lower()
    if extension == "scad":
        return scad_path

    out_path = f"generated_scad/{id}.{extension}"
    if os.path.exists(out_path):
        return out_path

    if extension not in {"stl"}:
        raise ValueError("Only scad/stl are supported in scad-v1 pipeline.")

    openscad_bin = _resolve_openscad_bin()
    if not openscad_bin:
        raise RuntimeError(
            "OpenSCAD CLI not found. Install OpenSCAD and add it to PATH, "
            "or set OPENSCAD_BIN to openscad.exe/openscad.com."
        )

    cmd = [openscad_bin, "-o", out_path, scad_path]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"OpenSCAD export failed: {proc.stderr.strip()}")
    return out_path
