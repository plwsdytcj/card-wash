"""
Read / write SillyTavern character cards from PNG, WebP, CHARX, and JSON.

PNG / APNG read/write is delegated to **card-forge** (``forge.helper``):
  • ``extract_card_data``  – reads ``ccv3`` / ``chara`` tEXt chunks
  • ``embed_card_data``    – writes both ``ccv3`` + ``chara`` (legacy=True)

WebP / CHARX / JSON are handled natively (card-forge doesn't cover these).
"""

from __future__ import annotations

import base64
import io
import json
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from forge.helper import embed_card_data, extract_card_data

from models import CharacterCard


# ═══════════════════════════════════════════════════════════════════════════════
#  PNG read / write  (via card-forge)
# ═══════════════════════════════════════════════════════════════════════════════


def read_card_from_png(data: bytes) -> CharacterCard:
    """
    Extract a CharacterCard from raw PNG / APNG bytes using card-forge.

    card-forge's ``extract_card_data`` handles ccv3 vs chara priority and
    v2 → v3 upgrade automatically.
    """
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name

    try:
        card_v3 = extract_card_data(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if card_v3 is None:
        raise ValueError(
            "PNG does not contain a 'chara' or 'ccv3' tEXt chunk"
        )

    # Convert forge's CharacterCardV3 → our CharacterCard
    raw = card_v3.model_dump()
    return CharacterCard.from_dict(raw)


def write_card_to_png(card: CharacterCard, original_png: bytes) -> bytes:
    """
    Inject the card JSON back into *original_png* using card-forge.

    Writes both ``ccv3`` (v3) and ``chara`` (v2 legacy) tEXt chunks via
    card-forge's ``embed_card_data(legacy=True)``.
    """
    v2_dict = card.to_v2_dict()
    metadata_json = json.dumps(v2_dict, ensure_ascii=False)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as src:
        src.write(original_png)
        src_path = src.name

    out_path = src_path + "_out.png"

    try:
        embed_card_data(metadata_json, src_path, out_path, legacy=True)
        result = Path(out_path).read_bytes()
    finally:
        Path(src_path).unlink(missing_ok=True)
        Path(out_path).unlink(missing_ok=True)

    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  WebP read
# ═══════════════════════════════════════════════════════════════════════════════


def read_card_from_webp(data: bytes) -> CharacterCard:
    """
    Extract character data from a WebP file's EXIF UserComment field.

    Many community tools (Chub, RisuAI, etc.) store the card JSON in the
    EXIF UserComment tag, either as raw UTF-8 or with the EXIF "UNICODE\\0"
    / "ASCII\\0\\0\\0" prefix.
    """
    try:
        from PIL import Image
    except ImportError:
        raise ImportError(
            "Pillow is required for WebP support. Install it with: "
            "pip install Pillow"
        )

    img = Image.open(io.BytesIO(data))
    exif = img.getexif()

    # UserComment tag = 0x9286 (37510)
    user_comment_tag = 0x9286
    raw_comment: bytes | str | None = None

    # Try main EXIF
    if user_comment_tag in exif:
        raw_comment = exif[user_comment_tag]
    else:
        # Try EXIF IFD
        for ifd_tag in exif.get_ifd(0x8769) or {}:
            if ifd_tag == user_comment_tag:
                raw_comment = exif.get_ifd(0x8769)[ifd_tag]
                break

    if raw_comment is None:
        raise ValueError("WebP does not contain EXIF UserComment data")

    # Decode
    if isinstance(raw_comment, bytes):
        # Strip EXIF encoding prefix if present
        # "ASCII\x00\x00\x00" (8 bytes) or "UNICODE\x00" (8 bytes)
        if raw_comment[:8] in (b"ASCII\x00\x00\x00", b"UNICODE\x00"):
            raw_comment = raw_comment[8:]
        text = raw_comment.decode("utf-8", errors="replace")
    else:
        text = str(raw_comment)

    text = text.strip().strip("\x00")

    # The data might be base64-encoded or raw JSON
    if text.startswith("{"):
        raw = json.loads(text)
    else:
        try:
            decoded = base64.b64decode(text).decode("utf-8")
            raw = json.loads(decoded)
        except Exception:
            raw = json.loads(text)

    return CharacterCard.from_dict(raw)


# ═══════════════════════════════════════════════════════════════════════════════
#  CHARX read
# ═══════════════════════════════════════════════════════════════════════════════


def read_card_from_charx(data: bytes) -> CharacterCard:
    """
    Extract character data from a ``.charx`` file (ZIP containing
    ``card.json`` at the root).
    """
    buf = io.BytesIO(data)
    try:
        with zipfile.ZipFile(buf, "r") as zf:
            if "card.json" not in zf.namelist():
                raise ValueError("CHARX archive does not contain card.json")
            card_json = zf.read("card.json").decode("utf-8")
    except zipfile.BadZipFile:
        raise ValueError("File is not a valid CHARX (ZIP) archive")

    raw = json.loads(card_json)
    return CharacterCard.from_dict(raw)


# ═══════════════════════════════════════════════════════════════════════════════
#  JSON read
# ═══════════════════════════════════════════════════════════════════════════════


def read_card_from_json(data: bytes | str) -> CharacterCard:
    """Parse a CharacterCard from raw JSON bytes or string."""
    text = data.decode("utf-8") if isinstance(data, bytes) else data
    raw = json.loads(text)
    return CharacterCard.from_dict(raw)


# ═══════════════════════════════════════════════════════════════════════════════
#  Unified read
# ═══════════════════════════════════════════════════════════════════════════════


def read_card(file_bytes: bytes, filename: str) -> CharacterCard:
    """Auto-detect format by extension and read."""
    ext = Path(filename).suffix.lower()
    if ext == ".png":
        return read_card_from_png(file_bytes)
    elif ext == ".webp":
        return read_card_from_webp(file_bytes)
    elif ext == ".charx":
        return read_card_from_charx(file_bytes)
    elif ext == ".json":
        return read_card_from_json(file_bytes)
    else:
        # Try formats in order: PNG → WebP → CHARX → JSON
        for reader in (
            read_card_from_png,
            read_card_from_webp,
            read_card_from_charx,
            read_card_from_json,
        ):
            try:
                return reader(file_bytes)
            except Exception:
                continue
        raise ValueError(f"Could not parse card from '{filename}'")


# ═══════════════════════════════════════════════════════════════════════════════
#  Write helpers
# ═══════════════════════════════════════════════════════════════════════════════


def write_card_to_json(card: CharacterCard) -> bytes:
    """Serialise a CharacterCard to pretty-printed JSON bytes."""
    return json.dumps(
        card.to_v2_dict(), ensure_ascii=False, indent=2
    ).encode("utf-8")


def extract_avatar_from_png(data: bytes) -> str:
    """Return a ``data:image/png;base64,...`` data-URI from PNG bytes."""
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def extract_avatar_from_webp(data: bytes) -> str:
    """Return a ``data:image/webp;base64,...`` data-URI from WebP bytes."""
    return "data:image/webp;base64," + base64.b64encode(data).decode("ascii")
