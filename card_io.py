"""
Read / write SillyTavern character cards from PNG (tEXt chunk) and JSON files.

PNG character cards embed a base64-encoded JSON blob inside a ``tEXt`` chunk
with keyword ``chara``.  This module handles the low-level binary parsing so
the rest of the app never has to worry about it.
"""

from __future__ import annotations

import base64
import io
import json
import struct
import zlib
from pathlib import Path
from typing import Any

from models import CharacterCard


# ═══════════════════════════════════════════════════════════════════════════════
#  PNG chunk-level helpers
# ═══════════════════════════════════════════════════════════════════════════════

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _read_chunks(data: bytes) -> list[dict[str, Any]]:
    """Parse *data* into a list of ``{type, data}`` dicts (raw PNG chunks)."""
    if data[:8] != PNG_SIGNATURE:
        raise ValueError("Not a valid PNG file")
    chunks: list[dict[str, Any]] = []
    pos = 8
    while pos < len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        chunk_type = data[pos + 4 : pos + 8].decode("ascii")
        chunk_data = data[pos + 8 : pos + 8 + length]
        # skip CRC (4 bytes)
        pos += 12 + length
        chunks.append({"type": chunk_type, "data": chunk_data})
    return chunks


def _make_chunk(chunk_type: str, chunk_data: bytes) -> bytes:
    """Build a single PNG chunk (length + type + data + CRC)."""
    raw_type = chunk_type.encode("ascii")
    crc = zlib.crc32(raw_type + chunk_data) & 0xFFFFFFFF
    return (
        struct.pack(">I", len(chunk_data))
        + raw_type
        + chunk_data
        + struct.pack(">I", crc)
    )


def _encode_chunks(chunks: list[dict[str, Any]]) -> bytes:
    """Reassemble a list of chunk dicts back into a full PNG byte string."""
    parts = [PNG_SIGNATURE]
    for c in chunks:
        parts.append(_make_chunk(c["type"], c["data"]))
    return b"".join(parts)


# ═══════════════════════════════════════════════════════════════════════════════
#  tEXt chunk helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _decode_text_chunk(data: bytes) -> tuple[str, str]:
    """Decode a ``tEXt`` chunk into (keyword, text)."""
    sep = data.index(b"\x00")
    keyword = data[:sep].decode("latin-1")
    text = data[sep + 1 :].decode("latin-1")
    return keyword, text


def _encode_text_chunk(keyword: str, text: str) -> bytes:
    """Encode a ``tEXt`` chunk from (keyword, text)."""
    return keyword.encode("latin-1") + b"\x00" + text.encode("latin-1")


# ═══════════════════════════════════════════════════════════════════════════════
#  Public API
# ═══════════════════════════════════════════════════════════════════════════════


def read_card_from_png(data: bytes) -> CharacterCard:
    """
    Extract a CharacterCard from raw PNG bytes.

    Looks for a ``tEXt`` chunk with keyword ``chara``, base64-decodes the
    value, then parses the resulting JSON.
    """
    chunks = _read_chunks(data)
    for c in chunks:
        if c["type"] == "tEXt":
            kw, txt = _decode_text_chunk(c["data"])
            if kw == "chara":
                json_str = base64.b64decode(txt).decode("utf-8")
                raw = json.loads(json_str)
                return CharacterCard.from_dict(raw)
    raise ValueError("PNG does not contain a 'chara' tEXt chunk")


def read_card_from_json(data: bytes | str) -> CharacterCard:
    """Parse a CharacterCard from raw JSON bytes or string."""
    text = data.decode("utf-8") if isinstance(data, bytes) else data
    raw = json.loads(text)
    return CharacterCard.from_dict(raw)


def read_card(file_bytes: bytes, filename: str) -> CharacterCard:
    """Auto-detect format by extension and read."""
    ext = Path(filename).suffix.lower()
    if ext == ".png":
        return read_card_from_png(file_bytes)
    elif ext in (".json",):
        return read_card_from_json(file_bytes)
    else:
        # Try PNG first, fall back to JSON
        try:
            return read_card_from_png(file_bytes)
        except Exception:
            return read_card_from_json(file_bytes)


def write_card_to_json(card: CharacterCard) -> bytes:
    """Serialise a CharacterCard to pretty-printed JSON bytes."""
    return json.dumps(card.to_v2_dict(), ensure_ascii=False, indent=2).encode("utf-8")


def write_card_to_png(card: CharacterCard, original_png: bytes) -> bytes:
    """
    Inject the card JSON back into *original_png* as a ``tEXt`` ``chara``
    chunk, replacing the old one if present.

    The image data itself is preserved byte-for-byte.
    """
    chunks = _read_chunks(original_png)

    # Remove any existing 'chara' tEXt chunks
    new_chunks: list[dict[str, Any]] = []
    for c in chunks:
        if c["type"] == "tEXt":
            kw, _ = _decode_text_chunk(c["data"])
            if kw == "chara":
                continue
        new_chunks.append(c)

    # Build new chara chunk
    json_bytes = json.dumps(card.to_v2_dict(), ensure_ascii=False).encode("utf-8")
    b64_text = base64.b64encode(json_bytes).decode("latin-1")
    chara_data = _encode_text_chunk("chara", b64_text)

    # Insert right before IEND
    iend_idx = next(
        (i for i, c in enumerate(new_chunks) if c["type"] == "IEND"), len(new_chunks)
    )
    new_chunks.insert(iend_idx, {"type": "tEXt", "data": chara_data})

    return _encode_chunks(new_chunks)


def extract_avatar_from_png(data: bytes) -> str:
    """Return a ``data:image/png;base64,...`` data-URI from PNG bytes."""
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")
