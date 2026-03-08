"""
Scans mintdocs/ for mermaid code blocks, extracts them to diagram-gen/sources/,
renders each to a PNG via mmdc, and places the output in mintdocs/images/diagrams/.

Usage:
    python diagram-gen/generate.py [--check]

    --check   Dry-run: exit with code 1 if any .mmd source is out of date
              (used by the pre-commit hook to detect stale extractions).
              Does NOT render images in check mode.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths (all relative to repo root, which is one level up from this script)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent
MINTDOCS_DIR = REPO_ROOT / "mintdocs"
SOURCES_DIR = Path(__file__).parent / "sources"
IMAGES_DIR = MINTDOCS_DIR / "images" / "diagrams"

# mmdc renders at this pixel width — wide enough for complex diagrams
RENDER_WIDTH = 2400

# Regex: matches a full mermaid fenced code block in MDX.
# The opening fence may have Mintlify props like: ```mermaid actions={true} placement="top-right"
# We capture only the diagram body (group 1).
_MERMAID_BLOCK_RE = re.compile(
    r"^```mermaid[^\n]*\n(.*?)^```",
    re.MULTILINE | re.DOTALL,
)


def slug(mdx_path: Path) -> str:
    """Return the MDX filename stem, e.g. 'architecture-overview'."""
    return mdx_path.stem


def source_path(mdx_path: Path, index: int) -> Path:
    return SOURCES_DIR / f"{slug(mdx_path)}--diagram-{index}.mmd"


def image_path(mdx_path: Path, index: int) -> Path:
    return IMAGES_DIR / f"{slug(mdx_path)}--diagram-{index}.png"


def image_url(mdx_path: Path, index: int) -> str:
    """Mintlify root-relative URL for the rendered image."""
    return f"/images/diagrams/{slug(mdx_path)}--diagram-{index}.png"


def extract_diagrams(mdx_path: Path) -> list[str]:
    """Return a list of mermaid diagram bodies found in an MDX file."""
    text = mdx_path.read_text(encoding="utf-8")
    return [m.group(1) for m in _MERMAID_BLOCK_RE.finditer(text)]


def ensure_dirs() -> None:
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)


def write_source(path: Path, body: str) -> bool:
    """Write .mmd file; return True if content changed."""
    new_content = body.rstrip("\n") + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == new_content:
        return False
    path.write_text(new_content, encoding="utf-8")
    return True


def _mmdc_cmd() -> list[str]:
    """
    Return the mmdc invocation that works on this platform.
    On Windows, npm global binaries are .cmd wrappers and need shell=True
    or must be invoked via 'cmd /c mmdc.cmd'. We use 'npx mmdc' as a
    reliable cross-platform fallback that works whether mmdc is globally
    installed or not.
    """
    if sys.platform == "win32":
        # mmdc.cmd lives in the npm global bin dir; npx finds it reliably
        return ["npx", "--yes", "mmdc"]
    return ["mmdc"]


def render_image(mmd_path: Path, png_path: Path) -> None:
    """Call mmdc to render mmd_path → png_path."""
    cmd = _mmdc_cmd() + [
        "-i", str(mmd_path),
        "-o", str(png_path),
        "-w", str(RENDER_WIDTH),
        "-b", "transparent",
    ]
    # shell=True required on Windows so .cmd wrappers resolve correctly
    result = subprocess.run(cmd, capture_output=True, text=True, shell=(sys.platform == "win32"))
    if result.returncode != 0:
        print(f"  [ERROR] mmdc failed for {mmd_path.name}:")
        print(result.stderr.strip())
        sys.exit(1)


def run(check_only: bool = False) -> None:
    ensure_dirs()

    mdx_files = sorted(MINTDOCS_DIR.glob("**/*.mdx"))
    stale: list[tuple[Path, int, str]] = []  # (mdx_path, index, body)

    for mdx_path in mdx_files:
        diagrams = extract_diagrams(mdx_path)
        for i, body in enumerate(diagrams, start=1):
            src = source_path(mdx_path, i)
            changed = write_source(src, body)
            if changed:
                stale.append((mdx_path, i, body))
                print(f"  [extracted] {src.name}")
            else:
                print(f"  [unchanged] {src.name}")

    if check_only:
        if stale:
            print(
                f"\n{len(stale)} diagram source(s) are out of date. "
                "Run `python diagram-gen/generate.py` to regenerate."
            )
            sys.exit(1)
        print("\nAll diagram sources are up to date.")
        return

    # Render every .mmd in sources/ (not just changed ones — mmdc is fast)
    mmd_files = sorted(SOURCES_DIR.glob("*.mmd"))
    if not mmd_files:
        print("\nNo .mmd files found — nothing to render.")
        return

    print(f"\nRendering {len(mmd_files)} diagram(s)...")
    for mmd_path in mmd_files:
        # Derive the MDX stem and index from the filename convention
        # e.g. architecture-overview--diagram-1.mmd
        parts = mmd_path.stem.rsplit("--diagram-", 1)
        if len(parts) != 2:
            print(f"  [skip] unexpected filename: {mmd_path.name}")
            continue
        png = IMAGES_DIR / f"{mmd_path.stem}.png"
        render_image(mmd_path, png)
        print(f"  [rendered] {png.name}")

    # Stage generated files so pre-commit's stash/restore cycle doesn't
    # conflict with the newly written PNGs and .mmd sources.
    generated = [str(p) for p in IMAGES_DIR.glob("*.png")] + [str(p) for p in SOURCES_DIR.glob("*.mmd")]
    if generated:
        subprocess.run(["git", "add", "--"] + generated, check=True)

    print("\nDone.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate PNG images from mermaid diagrams in mintdocs/")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Dry-run: exit 1 if any .mmd source is out of date (used by pre-commit hook)",
    )
    args = parser.parse_args()
    run(check_only=args.check)
