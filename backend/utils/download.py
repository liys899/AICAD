import os
import shutil
import subprocess


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

    openscad_bin = shutil.which("openscad")
    if not openscad_bin:
        raise RuntimeError("OpenSCAD CLI not found in PATH; install OpenSCAD to export STL.")

    cmd = [openscad_bin, "-o", out_path, scad_path]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"OpenSCAD export failed: {proc.stderr.strip()}")
    return out_path
