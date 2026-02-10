"""
Pydantic data models for SillyTavern character cards (v1 / v2).
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Lorebook / Character Book ────────────────────────────────────────────────


class LorebookEntry(BaseModel):
    keys: list[str] = Field(default_factory=list)
    content: str = ""
    extensions: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    insertion_order: int = 0
    case_sensitive: bool = False
    name: str = ""
    priority: int = 10
    id: int = 0
    comment: str = ""
    selective: bool = False
    secondary_keys: list[str] = Field(default_factory=list)
    constant: bool = False
    position: str = "before_char"


class Lorebook(BaseModel):
    entries: list[LorebookEntry] = Field(default_factory=list)
    name: str = ""
    description: str = ""
    scan_depth: int = 2
    token_budget: int = 500
    recursive_scanning: bool = False
    extensions: dict[str, Any] = Field(default_factory=dict)


# ── Character Card Data (v2 inner) ──────────────────────────────────────────


class CharacterCardData(BaseModel):
    """Fields shared across spec versions (v2 `data` block, v1 top-level)."""

    name: str = ""
    description: str = ""
    personality: str = ""
    scenario: str = ""
    first_mes: str = ""
    mes_example: str = ""

    # v2-specific
    creator_notes: str = ""
    system_prompt: str = ""
    post_history_instructions: str = ""
    alternate_greetings: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    creator: str = ""
    character_version: str = ""
    character_book: Optional[Lorebook] = None
    extensions: dict[str, Any] = Field(default_factory=dict)

    # v1 aliases (some older cards use these instead)
    char_name: str = ""
    char_persona: str = ""
    char_greeting: str = ""
    example_dialogue: str = ""
    world_scenario: str = ""

    class Config:
        extra = "allow"  # keep unknown fields


# ── Top-level Card Envelope ──────────────────────────────────────────────────


class CharacterCard(BaseModel):
    """
    Unified model that works for both v1 and v2 cards.

    • v2 cards have ``spec``, ``spec_version``, and ``data``.
    • v1 cards store everything at top-level; we normalise them into ``data``.
    """

    spec: str = "chara_card_v2"
    spec_version: str = "2.0"
    data: CharacterCardData = Field(default_factory=CharacterCardData)

    # Original avatar image as data-URI (png / webp), not part of the spec
    # but carried around for round-tripping.
    _avatar_data_uri: str = ""

    class Config:
        extra = "allow"

    # ── helpers ───────────────────────────────────────────────────────────

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CharacterCard":
        """Parse either v1 or v2 JSON dicts into a unified *CharacterCard*."""
        if "spec" in raw and "data" in raw:
            # v2 envelope
            return cls(**raw)
        # v1 – wrap into v2 shape
        return cls(
            spec="chara_card_v1",
            spec_version="1.0",
            data=CharacterCardData(**raw),
        )

    def to_v2_dict(self) -> dict[str, Any]:
        """Export as a v2-shaped dict ready for JSON / PNG embedding."""
        return {
            "spec": "chara_card_v2",
            "spec_version": "2.0",
            "data": self.data.model_dump(exclude_none=True),
        }

    # ── field access shortcuts ────────────────────────────────────────────

    @property
    def display_name(self) -> str:
        return self.data.name or self.data.char_name or "Unknown"

    # All text fields that can carry copyrighted content
    REWRITABLE_FIELDS: list[str] = [
        "name",
        "description",
        "personality",
        "scenario",
        "first_mes",
        "mes_example",
        "creator_notes",
        "system_prompt",
        "post_history_instructions",
    ]

    def get_rewritable_fields(self) -> dict[str, str]:
        """Return {field_name: value} for all non-empty rewritable text fields."""
        result: dict[str, str] = {}
        for f in self.REWRITABLE_FIELDS:
            val = getattr(self.data, f, "")
            if val and val.strip():
                result[f] = val
        return result
