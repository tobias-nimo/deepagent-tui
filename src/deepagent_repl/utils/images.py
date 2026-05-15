"""Image utilities — detection, encoding, and terminal inline rendering."""

from __future__ import annotations

import base64
import os
import re
import sys
from pathlib import Path

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".tiff", ".ico"}

# Regex to find file paths that look like images in text
_IMAGE_PATH_RE = re.compile(
    r"""(?:^|[\s"'(])(/[^\s"')]+\.(?:png|jpe?g|gif|bmp|webp|svg|tiff|ico))""",
    re.IGNORECASE,
)

# Match image paths as they typically arrive from a terminal drag-and-drop:
# single-quoted, double-quoted, or bare with backslash-escaped spaces.
_IMAGE_DROP_RE = re.compile(
    r"""
    (?:
        '(?P<sq>/[^']+?\.(?:png|jpe?g|gif|bmp|webp|svg|tiff|ico))'
        |
        "(?P<dq>/[^"]+?\.(?:png|jpe?g|gif|bmp|webp|svg|tiff|ico))"
        |
        (?P<bare>/(?:[^\s'"\\]|\\.)+?\.(?:png|jpe?g|gif|bmp|webp|svg|tiff|ico))(?=$|[\s)"',;])
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def is_image_path(path: str) -> bool:
    """Check if a path looks like an image file."""
    return Path(path).suffix.lower() in IMAGE_EXTENSIONS


def detect_image_paths(text: str) -> list[str]:
    """Extract file paths that look like images from a text string."""
    matches = _IMAGE_PATH_RE.findall(text)
    return [m for m in matches if Path(m).exists()]


def extract_image_paths(text: str) -> tuple[str, list[str]]:
    """Pull dropped image paths out of a message. Returns the message with
    the path tokens removed (whitespace collapsed) and the list of resolved
    paths. Only existing files with image extensions are returned."""
    paths: list[str] = []
    spans: list[tuple[int, int]] = []
    for m in _IMAGE_DROP_RE.finditer(text):
        raw = m.group("sq") or m.group("dq") or m.group("bare")
        if not raw:
            continue
        clean = raw.replace("\\ ", " ").replace("\\\\", "\\")
        p = Path(clean).expanduser()
        if p.is_file() and is_image_path(str(p)):
            paths.append(str(p))
            spans.append(m.span())

    cleaned = text
    for start, end in reversed(spans):
        cleaned = cleaned[:start] + cleaned[end:]
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned, paths


def encode_image_base64(path: str) -> str:
    """Read an image file and return its base64-encoded content."""
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


def get_image_media_type(path: str) -> str:
    """Return the MIME type for an image file."""
    ext = Path(path).suffix.lower()
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
        ".tiff": "image/tiff",
        ".ico": "image/x-icon",
    }
    return media_types.get(ext, "image/png")


def build_multimodal_content(text: str, image_paths: list[str]) -> list[dict]:
    """Build a multimodal content list with text and base64-encoded images."""
    content: list[dict] = []

    for path in image_paths:
        try:
            b64 = encode_image_base64(path)
            media_type = get_image_media_type(path)
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{media_type};base64,{b64}"},
            })
        except Exception:
            pass

    if text.strip():
        content.append({"type": "text", "text": text})

    return content


# --- Terminal image protocol detection and rendering ---

class _TerminalImageSupport:
    """Cached detection of terminal image capabilities."""

    def __init__(self):
        self._protocol: str | None = None
        self._detected = False

    @property
    def protocol(self) -> str | None:
        """Return 'iterm2', 'kitty', or None."""
        if not self._detected:
            self._protocol = self._detect()
            self._detected = True
        return self._protocol

    def _detect(self) -> str | None:
        term_program = os.environ.get("TERM_PROGRAM", "")
        term = os.environ.get("TERM", "")
        lc_terminal = os.environ.get("LC_TERMINAL", "")

        # iTerm2
        if "iTerm" in term_program or "iTerm" in lc_terminal:
            return "iterm2"

        # Kitty
        if "kitty" in term or "kitty" in term_program:
            return "kitty"

        # WezTerm supports iTerm2 protocol
        if "WezTerm" in term_program:
            return "iterm2"

        return None


_terminal = _TerminalImageSupport()


def can_render_inline() -> bool:
    """Check if the terminal supports inline image rendering."""
    return _terminal.protocol is not None


def render_image_inline(path: str, max_width: int = 80) -> str | None:
    """Render an image inline in the terminal using escape sequences.

    Returns the escape sequence string, or None if not supported.
    """
    protocol = _terminal.protocol
    if protocol is None:
        return None

    try:
        data = Path(path).read_bytes()
    except Exception:
        return None

    if protocol == "iterm2":
        return _render_iterm2(data, Path(path).name, max_width)
    elif protocol == "kitty":
        return _render_kitty(data)

    return None


def _render_iterm2(data: bytes, filename: str, max_width: int) -> str:
    """iTerm2 inline image protocol."""
    b64 = base64.b64encode(data).decode("ascii")
    # OSC 1337 ; File=[args]:base64data ST
    params = f"name={base64.b64encode(filename.encode()).decode()};size={len(data)};inline=1;width={max_width}"
    return f"\033]1337;File={params}:{b64}\a"


def _render_kitty(data: bytes) -> str:
    """Kitty graphics protocol — transmit image in chunks."""
    b64 = base64.b64encode(data).decode("ascii")
    chunks = [b64[i : i + 4096] for i in range(0, len(b64), 4096)]
    parts: list[str] = []
    for i, chunk in enumerate(chunks):
        is_last = i == len(chunks) - 1
        m = 0 if is_last else 1
        if i == 0:
            parts.append(f"\033_Ga=T,f=100,m={m};{chunk}\033\\")
        else:
            parts.append(f"\033_Gm={m};{chunk}\033\\")
    return "".join(parts)


def write_inline_image(path: str) -> bool:
    """Write an image inline to stdout. Returns True if rendered, False if unsupported."""
    seq = render_image_inline(path)
    if seq is None:
        return False
    sys.stdout.write(seq)
    sys.stdout.write("\n")
    sys.stdout.flush()
    return True
