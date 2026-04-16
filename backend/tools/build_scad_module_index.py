from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

MODULE_START_RE = re.compile(r"^\s*module\s+([A-Za-z_]\w*)\s*\(")


def _split_args(raw: str) -> list[str]:
    if not raw.strip():
        return []
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    in_str = False
    esc = False
    for ch in raw:
        if in_str:
            buf.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            buf.append(ch)
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _parse_arg_names(raw: str) -> list[str]:
    names: list[str] = []
    for item in _split_args(raw):
        if not item:
            continue
        lhs = item.split("=", 1)[0].strip()
        lhs = lhs.lstrip("*")
        if re.match(r"^[A-Za-z_]\w*$", lhs):
            names.append(lhs)
    return names


def _scan_file(path: Path, root: Path) -> list[dict]:
    out: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return out
    idx = 0
    total = len(lines)
    while idx < total:
        line = lines[idx]
        m = MODULE_START_RE.match(line)
        if not m:
            idx += 1
            continue
        module_name = m.group(1)
        start_line = idx + 1
        signature_lines = [line.rstrip()]
        paren_balance = line.count("(") - line.count(")")
        while paren_balance > 0 and idx + 1 < total:
            idx += 1
            nxt = lines[idx]
            signature_lines.append(nxt.rstrip())
            paren_balance += nxt.count("(") - nxt.count(")")
        signature_text = " ".join(x.strip() for x in signature_lines)
        args_raw = ""
        open_idx = signature_text.find("(")
        close_idx = signature_text.rfind(")")
        if open_idx >= 0 and close_idx > open_idx:
            args_raw = signature_text[open_idx + 1 : close_idx]
        out.append(
            {
                "module": module_name,
                "args": _parse_arg_names(args_raw),
                "signature": signature_text.strip(),
                "line": start_line,
                "path": str(path.relative_to(root)).replace("\\", "/"),
            }
        )
        idx += 1
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan *.scad modules and build JSON index.")
    parser.add_argument(
        "--root",
        default=str((Path(__file__).resolve().parents[1] / "openscad_vendor")),
        help="Root directory to recursively scan (*.scad).",
    )
    parser.add_argument(
        "--out",
        default=str((Path(__file__).resolve().parents[1] / "openscad_vendor" / "scad_module_index.json")),
        help="Output JSON index path.",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out_path = Path(args.out).resolve()
    if not root.exists():
        raise SystemExit(f"Scan root not found: {root}")

    entries: list[dict] = []
    for scad_file in sorted(root.rglob("*.scad")):
        entries.extend(_scan_file(scad_file, root))
    payload = {
        "root": str(root).replace("\\", "/"),
        "total_files": len({e["path"] for e in entries}),
        "total_modules": len(entries),
        "modules": entries,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Indexed {payload['total_modules']} modules from {payload['total_files']} files.")
    print(f"Output: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
