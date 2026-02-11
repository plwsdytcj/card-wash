"""
LLM-based rewriting engine for character card fields.

Supports:
  • OpenAI API (gpt-4o, gpt-4o-mini, etc.)
  • Anthropic Claude API (claude-3.5-sonnet, etc.)
  • Any OpenAI-compatible endpoint (Ollama, vLLM, LM Studio, etc.)

Three rewrite strength levels:
  • light   – only replace explicit names and direct references
  • medium  – also adapt world/setting, keep personality and style
  • heavy   – fully transform into an original character
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from models import CharacterCard


class RewriteStrength(str, Enum):
    LIGHT = "light"
    MEDIUM = "medium"
    HEAVY = "heavy"


class LLMProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OPENAI_COMPATIBLE = "openai_compatible"


@dataclass
class LLMConfig:
    provider: LLMProvider = LLMProvider.OPENAI
    api_key: str = ""
    model: str = "gpt-4o-mini"
    base_url: Optional[str] = None  # for OpenAI-compatible endpoints
    temperature: float = 0.7
    max_tokens: int = 4096


# ═══════════════════════════════════════════════════════════════════════════════
#  Prompt templates
# ═══════════════════════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = """\
You are an expert character card editor for AI roleplay. Your job is to \
rewrite character card fields to remove copyrighted material while preserving \
the essence of the character. You MUST output valid JSON and nothing else.

RULES:
1. Preserve the character's core personality traits, speaking style, and \
   interaction patterns.
2. Replace all copyrighted names, places, organizations, and lore with \
   original alternatives that feel natural.
3. Keep the same tone, length, and formatting as the original.
4. Do NOT add disclaimers, notes, or commentary.
5. If the field uses {{user}} or {{char}} macros, keep them as-is.
6. Output a JSON object with the same field keys as the input.
"""

_STRENGTH_INSTRUCTIONS = {
    RewriteStrength.LIGHT: """\
REWRITE STRENGTH: LIGHT
- Only replace explicit character names and direct IP references.
- Keep personality descriptions, scenario structure, and dialogue style unchanged.
- Minimal changes — just enough to avoid direct name matches.""",
    RewriteStrength.MEDIUM: """\
REWRITE STRENGTH: MEDIUM
- Replace all character names, place names, organization names, and world-specific terms.
- Adapt the background story to remove franchise connections while keeping the same narrative arc.
- Preserve personality traits, speaking style, and relationship dynamics exactly.
- The character should feel like a spiritual successor, not a copy.""",
    RewriteStrength.HEAVY: """\
REWRITE STRENGTH: HEAVY
- Fully transform into an original character.
- Only preserve the core personality archetype and interaction patterns.
- Create entirely new names, backstory, world setting, and lore.
- The character should be unrecognizable as derived from the original IP.
- Be creative — make the new character interesting in their own right.""",
}

# Language-specific instructions appended to the prompt
_LANGUAGE_INSTRUCTIONS = {
    "en": "Write the rewritten content in English.",
    "zh": (
        "用中文书写改写后的内容。保持原文的中文表达风格、语气和用词习惯。"
        "替换的名称也应使用自然的中文名称。"
    ),
    "ja": (
        "書き換えた内容は日本語で記述してください。"
        "原文の日本語表現スタイル、口調、語彙の特徴を維持してください。"
        "置き換える名前も自然な日本語名にしてください。"
    ),
    "ko": (
        "다시 작성한 내용은 한국어로 작성하세요. "
        "원문의 한국어 표현 스타일, 어조, 어휘 특성을 유지하세요. "
        "대체하는 이름도 자연스러운 한국어 이름으로 해주세요."
    ),
    "mixed": (
        "The original content is multilingual. Rewrite each field in the SAME "
        "language as its original text. If a field mixes languages, keep the "
        "same language mix. Do NOT translate between languages."
    ),
}


def _build_user_prompt(
    fields: dict[str, str],
    strength: RewriteStrength,
    language: str = "en",
) -> str:
    instruction = _STRENGTH_INSTRUCTIONS[strength]
    lang_instruction = _LANGUAGE_INSTRUCTIONS.get(
        language, _LANGUAGE_INSTRUCTIONS["en"]
    )
    fields_json = json.dumps(fields, ensure_ascii=False, indent=2)
    return f"""{instruction}

LANGUAGE: {lang_instruction}

Here are the character card fields to rewrite. Return a JSON object with the \
same keys, where each value is the rewritten version.

```json
{fields_json}
```"""


# ═══════════════════════════════════════════════════════════════════════════════
#  LLM calling
# ═══════════════════════════════════════════════════════════════════════════════


async def _call_openai(
    config: LLMConfig, system: str, user: str
) -> str:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
    )
    resp = await client.chat.completions.create(
        model=config.model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )
    return resp.choices[0].message.content or ""


async def _call_anthropic(
    config: LLMConfig, system: str, user: str
) -> str:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=config.api_key)
    resp = await client.messages.create(
        model=config.model,
        max_tokens=config.max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        temperature=config.temperature,
    )
    return resp.content[0].text


async def _call_llm(config: LLMConfig, system: str, user: str) -> str:
    if config.provider == LLMProvider.ANTHROPIC:
        return await _call_anthropic(config, system, user)
    else:
        # Both OPENAI and OPENAI_COMPATIBLE use the OpenAI SDK
        return await _call_openai(config, system, user)


def _extract_json(raw: str) -> dict[str, str]:
    """Extract JSON from LLM response, handling markdown code fences."""
    text = raw.strip()
    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # remove opening fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return json.loads(text)


# ═══════════════════════════════════════════════════════════════════════════════
#  Public API
# ═══════════════════════════════════════════════════════════════════════════════


async def rewrite_fields(
    fields: dict[str, str],
    strength: RewriteStrength,
    config: LLMConfig,
    language: str = "en",
) -> dict[str, str]:
    """
    Rewrite the given field dict using the configured LLM.

    *language* should be one of ``"en"``, ``"zh"``, ``"ja"``, ``"ko"``, ``"mixed"``.
    The LLM is instructed to write the rewritten content in the same language.

    Returns a dict with the same keys, values replaced with rewritten text.
    """
    system = _SYSTEM_PROMPT
    user = _build_user_prompt(fields, strength, language)

    raw_response = await _call_llm(config, system, user)
    rewritten = _extract_json(raw_response)

    # Ensure all original keys are present
    result: dict[str, str] = {}
    for key in fields:
        result[key] = rewritten.get(key, fields[key])
    return result


async def rewrite_card(
    card: CharacterCard,
    strength: RewriteStrength,
    config: LLMConfig,
    selected_fields: Optional[list[str]] = None,
    language: str = "en",
) -> dict[str, Any]:
    """
    Rewrite the card and return a diff-friendly result.

    *language* is auto-detected by the analyser and passed through so
    the LLM rewrites in the same language as the original card.

    Returns::

        {
            "original": {field: old_value, ...},
            "rewritten": {field: new_value, ...},
        }
    """
    all_fields = card.get_rewritable_fields()
    if selected_fields:
        fields = {k: v for k, v in all_fields.items() if k in selected_fields}
    else:
        fields = all_fields

    if not fields:
        return {"original": {}, "rewritten": {}}

    rewritten = await rewrite_fields(fields, strength, config, language)
    return {
        "original": fields,
        "rewritten": rewritten,
    }


def apply_rewrite(card: CharacterCard, rewritten_fields: dict[str, str]) -> CharacterCard:
    """Apply rewritten field values back onto the card (mutates in place)."""
    for field_name, new_value in rewritten_fields.items():
        if hasattr(card.data, field_name):
            setattr(card.data, field_name, new_value)
    return card


# ═══════════════════════════════════════════════════════════════════════════════
#  Translation
# ═══════════════════════════════════════════════════════════════════════════════

_LANG_NAMES = {"zh": "中文", "en": "English", "ja": "日本語"}

_TRANSLATE_SYSTEM = """\
You are an expert translator specializing in AI roleplay character cards. \
Your job is to translate character card fields from one language to another \
while preserving the character's personality, tone, and all formatting. \
You MUST output valid JSON and nothing else.

RULES:
1. Translate ALL text content naturally — not word-by-word literal translation.
2. Adapt names to feel natural in the target language:
   - Chinese names → keep or transliterate appropriately for target language.
   - Japanese names → keep original or romanize depending on target language norms.
   - English names → transliterate naturally into target language.
3. Preserve {{user}}, {{char}}, and any other macros/placeholders EXACTLY as-is.
4. Keep all HTML tags, XML-like tags (e.g. <CoreIdentity>), and formatting intact.
5. Maintain the same length, level of detail, and writing quality.
6. Do NOT add disclaimers, translator notes, or commentary.
7. Dialogue and speech patterns should feel native in the target language, not translated.
8. Output a JSON object with the same field keys as the input."""


def _build_translate_prompt(
    fields: dict[str, str],
    source_lang: str,
    target_lang: str,
) -> str:
    src_name = _LANG_NAMES.get(source_lang, source_lang)
    tgt_name = _LANG_NAMES.get(target_lang, target_lang)
    fields_json = json.dumps(fields, ensure_ascii=False, indent=2)
    return f"""Translate the following character card fields from {src_name} to {tgt_name}.

The translation should read as if the card was originally written in {tgt_name}. \
Adapt cultural references, idioms, and speech patterns to feel native.

Return a JSON object with the same keys, where each value is the translated version.

```json
{fields_json}
```"""


async def translate_fields(
    fields: dict[str, str],
    source_lang: str,
    target_lang: str,
    config: LLMConfig,
) -> dict[str, str]:
    """
    Translate fields from *source_lang* to *target_lang* using the configured LLM.

    Supported languages: ``"zh"``, ``"en"``, ``"ja"``.
    """
    system = _TRANSLATE_SYSTEM
    user = _build_translate_prompt(fields, source_lang, target_lang)

    raw_response = await _call_llm(config, system, user)
    translated = _extract_json(raw_response)

    result: dict[str, str] = {}
    for key in fields:
        result[key] = translated.get(key, fields[key])
    return result


async def translate_card(
    card: CharacterCard,
    source_lang: str,
    target_lang: str,
    config: LLMConfig,
    selected_fields: Optional[list[str]] = None,
) -> dict[str, Any]:
    """
    Translate the card and return a diff-friendly result.

    Returns::

        {
            "original": {field: old_value, ...},
            "translated": {field: new_value, ...},
            "source_lang": "zh",
            "target_lang": "en",
        }
    """
    all_fields = card.get_rewritable_fields()
    if selected_fields:
        fields = {k: v for k, v in all_fields.items() if k in selected_fields}
    else:
        fields = all_fields

    if not fields:
        return {"original": {}, "translated": {}, "source_lang": source_lang, "target_lang": target_lang}

    translated = await translate_fields(fields, source_lang, target_lang, config)
    return {
        "original": fields,
        "translated": translated,
        "source_lang": source_lang,
        "target_lang": target_lang,
    }
