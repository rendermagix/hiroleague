"""QR code rendering helpers.

Two output modes:
  - render_qr_terminal(payload)  — prints a Unicode-block QR code to stdout
                                    (works on Windows / macOS / Linux)
  - render_qr_svg(payload) -> str — returns an inline SVG string for browser UIs
"""

from __future__ import annotations

import io
import sys
import xml.etree.ElementTree as ET

import qrcode
import qrcode.image.svg


def render_qr_terminal(payload: str) -> None:
    """Print a QR code for *payload* to stdout.

    Writes Unicode block characters as UTF-8 bytes directly to stdout.buffer
    to bypass Windows cp1252 codec restrictions.  Falls back to doubled ASCII
    '##' / '  ' characters when stdout.buffer is unavailable.
    """
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=1,
        border=2,
    )
    qr.add_data(payload)
    qr.make(fit=True)

    buf = io.StringIO()
    qr.print_ascii(out=buf, invert=True)
    content = buf.getvalue()

    try:
        # Write UTF-8 bytes directly — avoids Windows cp1252 UnicodeEncodeError
        sys.stdout.buffer.write(content.encode("utf-8"))
        sys.stdout.buffer.flush()
    except AttributeError:
        # stdout.buffer unavailable (e.g. some IDE consoles); use ASCII fallback
        matrix = qr.get_matrix()
        for row in matrix:
            print("".join("##" if cell else "  " for cell in row))


def render_qr_svg(payload: str) -> str:
    """Return a self-contained SVG string encoding *payload*.

    Uses qrcode's built-in SVG backend (no Pillow / lxml required).
    The SVG has no fixed width/height so the caller can size it via CSS.
    """
    factory = qrcode.image.svg.SvgPathFillImage
    img = qrcode.make(
        payload,
        image_factory=factory,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        border=2,
    )
    buf = io.BytesIO()
    img.save(buf)
    svg_bytes = buf.getvalue()

    # Register the SVG namespace as the default (empty prefix) so ET serializes
    # <svg xmlns="..."> instead of <svg:svg xmlns:svg="...">.
    # Browsers only render inline SVG when the default namespace is used.
    ET.register_namespace("", "http://www.w3.org/2000/svg")

    # Remove fixed width/height so the SVG scales with its container
    root = ET.fromstring(svg_bytes.decode("utf-8"))
    root.attrib.pop("width", None)
    root.attrib.pop("height", None)
    root.set("viewBox", root.attrib.get("viewBox", "0 0 100 100"))

    return ET.tostring(root, encoding="unicode")
