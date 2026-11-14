"""Collect the licence texts of everything the exe bundles into one THIRD_PARTY_NOTICES.txt
"""
import importlib.metadata as md
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "notices" / "THIRD_PARTY_NOTICES.txt"
BUILD_ONLY = {"pip", "setuptools", "wheel", "pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "pefile",
              "pywin32-ctypes", "packaging", "pytest", "iniconfig", "pluggy", "colorama"}
LICENCE_NAMES = ("license", "licence", "copying", "notice", "authors")


def licence_files(dist):
    found = []
    for f in dist.files or []:
        name = f.name.lower()
        in_licence_dir = any(part.lower() in ("licenses", "licences") for part in f.parts[:-1])
        if ".dist-info" in str(f) and (in_licence_dir or name.startswith(LICENCE_NAMES)):
            path = Path(dist.locate_file(f))
            if path.is_file():
                found.append(path)
    return found


def main():
    blocks = []
    dists = sorted(md.distributions(), key=lambda d: d.metadata["Name"].lower())
    for dist in dists:
        name = dist.metadata["Name"]
        if name.lower() in BUILD_ONLY:
            continue
        texts = []
        for path in licence_files(dist):
            texts.append(path.read_text(encoding="utf-8", errors="replace").strip())
        if not texts:
            declared = dist.metadata.get("License-Expression") or dist.metadata.get("License") or "see the project"
            texts.append(f"Licence: {declared.strip()[:300]}")
        blocks.append((f"{name} {dist.version}", "\n\n".join(texts)))

    python_licence = Path(sys.base_prefix) / "LICENSE.txt"
    if python_licence.is_file():
        blocks.insert(0, (f"Python {sys.version.split()[0]}", python_licence.read_text(encoding="utf-8", errors="replace").strip()))

    line = "=" * 79
    body = [
        "MKWorld Mogi Tracker includes the open-source software listed below.",
        "The app's licence, the bundled fonts and the OCR model (including its PaddleOCR origin, Apache License 2.0)",
        "are described in LICENSE.",
        "",
        "Included: " + ", ".join(title for title, _ in blocks),
        "",
    ]
    for title, text in blocks:
        body += [line, title, line, "", text, ""]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(body), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(blocks)} components, {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
