from __future__ import annotations

import importlib.metadata as md
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / "vendor"

ROOTS = [
    "fastapi",
    "uvicorn",
    "python-multipart",
    "qrcode",
    "pillow",
]

NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+")


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_req_name(req: str) -> str | None:
    req = req.split(";", 1)[0].strip()
    m = NAME_RE.match(req)
    return norm(m.group(0)) if m else None


def main() -> None:
    installed: dict[str, md.Distribution] = {}
    for dist in md.distributions():
        name = dist.metadata.get("Name")
        if name:
            installed[norm(name)] = dist

    wanted: dict[str, md.Distribution] = {}

    def add_dist(name: str) -> None:
        key = norm(name)
        dist = installed.get(key)
        if not dist or key in wanted:
            return
        wanted[key] = dist
        for req in dist.requires or []:
            dep_key = parse_req_name(req)
            if dep_key and dep_key in installed:
                add_dist(dep_key)

    for name in ROOTS:
        add_dist(name)

    VENDOR.mkdir(parents=True, exist_ok=True)
    for child in VENDOR.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()

    copied = 0
    for dist in wanted.values():
        files = dist.files or []
        for file in files:
            if ".." in file.parts:
                continue
            src = dist.locate_file(file)
            if not src.exists():
                continue
            dest = VENDOR / file
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                if not dest.exists():
                    shutil.copytree(src, dest, symlinks=False)
            else:
                shutil.copy2(src, dest)
            copied += 1

    print(f"Vendor prepared: {VENDOR}")
    print(f"Distributions copied: {len(wanted)}")
    print(f"Files copied: {copied}")


if __name__ == "__main__":
    main()
