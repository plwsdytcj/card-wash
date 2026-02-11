#!/usr/bin/env python3
"""
Card Wash — CLI 批量处理脚本

用法:
  python3 batch.py ./input_cards/ -o ./output_cards/ \
      --provider openai --api-key sk-xxx --model gpt-4o-mini \
      --strength medium --fields name,description,personality,scenario,first_mes

支持:
  • 处理整个目录下的 .png / .json 角色卡
  • 自动跳过已处理的文件
  • 进度显示 + 最终汇总报告
  • 输出到指定目录，保留原文件名 + _washed 后缀
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from analyzer import analyse_card
from card_io import read_card, write_card_to_json, write_card_to_png
from models import CharacterCard
from rewriter import (
    LLMConfig,
    LLMProvider,
    RewriteStrength,
    apply_rewrite,
    rewrite_card,
    translate_card,
)


# ── Colors for terminal ──────────────────────────────────────────────────

class C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    RED    = "\033[31m"
    GREEN  = "\033[32m"
    YELLOW = "\033[33m"
    BLUE   = "\033[34m"
    CYAN   = "\033[36m"


def log(icon: str, msg: str, color: str = ""):
    print(f"  {color}{icon}{C.RESET} {msg}")


def header(msg: str):
    w = 60
    print(f"\n{C.CYAN}{'━' * w}")
    print(f"  {C.BOLD}{msg}{C.RESET}")
    print(f"{C.CYAN}{'━' * w}{C.RESET}\n")


# ── Core logic ────────────────────────────────────────────────────────────

async def process_one(
    filepath: Path,
    output_dir: Path,
    config: LLMConfig,
    strength: RewriteStrength,
    selected_fields: list[str] | None,
    output_format: str,
    force_rewrite: bool = False,
) -> dict:
    """Process a single card file. Returns a result dict."""
    result = {
        "file": filepath.name,
        "status": "ok",
        "risk_before": 0,
        "risk_after": 0,
        "fields_rewritten": 0,
        "error": "",
    }

    try:
        file_bytes = filepath.read_bytes()
        card = read_card(file_bytes, filepath.name)

        # Analyse before
        analysis_before = analyse_card(card)
        result["risk_before"] = analysis_before.overall_risk

        # Skip if no risk detected (unless force rewrite)
        if analysis_before.overall_risk == 0 and not force_rewrite:
            result["status"] = "skipped"
            # Still copy to output
            _write_output(card, file_bytes, filepath, output_dir, output_format)
            return result

        # Detect language and rewrite in the same language
        from analyzer import detect_language as _detect_lang
        lang_sample = " ".join(
            v for k, v in card.get_rewritable_fields().items()
            if k in ("description", "personality", "scenario", "first_mes")
        )
        detected_lang = _detect_lang(lang_sample)
        rw = await rewrite_card(card, strength, config, selected_fields, detected_lang)
        if rw["rewritten"]:
            apply_rewrite(card, rw["rewritten"])
            result["fields_rewritten"] = len(rw["rewritten"])

        # Analyse after
        analysis_after = analyse_card(card)
        result["risk_after"] = analysis_after.overall_risk

        # Write output
        _write_output(card, file_bytes, filepath, output_dir, output_format)

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    return result


def _write_output(
    card: CharacterCard,
    original_bytes: bytes,
    original_path: Path,
    output_dir: Path,
    output_format: str,
    suffix: str = "_washed",
):
    stem = original_path.stem
    if output_format == "png" and original_path.suffix.lower() == ".png":
        out_path = output_dir / f"{stem}{suffix}.png"
        out_bytes = write_card_to_png(card, original_bytes)
    else:
        out_path = output_dir / f"{stem}{suffix}.json"
        out_bytes = write_card_to_json(card)
    out_path.write_bytes(out_bytes)


async def translate_one(
    filepath: Path,
    output_dir: Path,
    config: LLMConfig,
    target_lang: str,
    selected_fields: list[str] | None,
    output_format: str,
) -> dict:
    """Translate a single card file. Returns a result dict."""
    result = {
        "file": filepath.name,
        "status": "ok",
        "source_lang": "",
        "target_lang": target_lang,
        "fields_translated": 0,
        "error": "",
    }

    try:
        file_bytes = filepath.read_bytes()
        card = read_card(file_bytes, filepath.name)

        # Detect source language
        from analyzer import detect_language as _detect_lang
        lang_sample = " ".join(
            v for k, v in card.get_rewritable_fields().items()
            if k in ("description", "personality", "scenario", "first_mes")
        )
        source_lang = _detect_lang(lang_sample)
        result["source_lang"] = source_lang

        if source_lang == target_lang:
            result["status"] = "skipped"
            _write_output(card, file_bytes, filepath, output_dir, output_format, "_translated")
            return result

        tr = await translate_card(card, source_lang, target_lang, config, selected_fields)
        if tr["translated"]:
            apply_rewrite(card, tr["translated"])
            result["fields_translated"] = len(tr["translated"])

        _write_output(card, file_bytes, filepath, output_dir, output_format, "_translated")

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    return result


async def batch_process(args: argparse.Namespace):
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Collect files
    files = sorted([
        f for f in input_dir.iterdir()
        if f.suffix.lower() in (".png", ".webp", ".charx", ".json")
        and not f.name.startswith(".")
    ])

    if not files:
        log("!", f"在 {input_dir} 中没有找到 .png / .webp / .charx / .json 文件", C.YELLOW)
        return

    header(f"Card Wash 批量处理 — {len(files)} 个文件")

    # Config
    try:
        provider = LLMProvider(args.provider)
    except ValueError:
        provider = LLMProvider.OPENAI_COMPATIBLE

    config = LLMConfig(
        provider=provider,
        api_key=args.api_key,
        model=args.model,
        base_url=args.base_url,
        temperature=args.temperature,
    )

    try:
        strength = RewriteStrength(args.strength)
    except ValueError:
        strength = RewriteStrength.MEDIUM

    selected_fields = (
        [f.strip() for f in args.fields.split(",") if f.strip()]
        if args.fields
        else None
    )

    log("⚙", f"提供商: {provider.value}  模型: {args.model}", C.DIM)
    log("⚙", f"改写强度: {strength.value}  Temperature: {args.temperature}", C.DIM)
    if selected_fields:
        log("⚙", f"指定字段: {', '.join(selected_fields)}", C.DIM)
    else:
        log("⚙", f"字段: 所有非空可改写字段", C.DIM)
    log("⚙", f"输出目录: {output_dir}", C.DIM)
    print()

    # Process
    results = []
    total = len(files)
    t0 = time.time()

    for i, fp in enumerate(files, 1):
        prefix = f"[{i}/{total}]"

        # Check if already processed
        washed_name_json = output_dir / f"{fp.stem}_washed.json"
        washed_name_png = output_dir / f"{fp.stem}_washed.png"
        if not args.force and (washed_name_json.exists() or washed_name_png.exists()):
            log("→", f"{prefix} {C.DIM}{fp.name} — 已存在，跳过{C.RESET}")
            results.append({
                "file": fp.name,
                "status": "exists",
                "risk_before": 0,
                "risk_after": 0,
                "fields_rewritten": 0,
                "error": "",
            })
            continue

        log("▶", f"{prefix} {fp.name} ...", C.BLUE)

        res = await process_one(fp, output_dir, config, strength, selected_fields, args.format, args.force_rewrite)
        results.append(res)

        if res["status"] == "ok":
            risk_arrow = f"{res['risk_before']} → {res['risk_after']}"
            color = C.GREEN if res["risk_after"] < res["risk_before"] else C.YELLOW
            log("✓", f"{prefix} {fp.name}  风险: {color}{risk_arrow}{C.RESET}  改写 {res['fields_rewritten']} 个字段", C.GREEN)
        elif res["status"] == "skipped":
            log("○", f"{prefix} {fp.name}  无风险，已复制", C.DIM)
        elif res["status"] == "error":
            log("✗", f"{prefix} {fp.name}  {C.RED}错误: {res['error']}{C.RESET}", C.RED)

        # Rate limit: small delay between API calls
        if i < total and res["status"] == "ok":
            await asyncio.sleep(args.delay)

    elapsed = time.time() - t0

    # ── Summary ───────────────────────────────────────────────────────────
    header("处理完成")

    ok_count = sum(1 for r in results if r["status"] == "ok")
    skip_count = sum(1 for r in results if r["status"] in ("skipped", "exists"))
    err_count = sum(1 for r in results if r["status"] == "error")

    log("📊", f"总计: {total} 个文件")
    log("✓", f"成功改写: {C.GREEN}{ok_count}{C.RESET}")
    log("○", f"跳过: {C.DIM}{skip_count}{C.RESET}")
    if err_count:
        log("✗", f"错误: {C.RED}{err_count}{C.RESET}")
    log("⏱", f"耗时: {elapsed:.1f}s")
    log("📁", f"输出目录: {output_dir}")

    # Write report
    report_path = output_dir / "_batch_report.json"
    report = {
        "total": total,
        "ok": ok_count,
        "skipped": skip_count,
        "errors": err_count,
        "elapsed_seconds": round(elapsed, 1),
        "config": {
            "provider": provider.value,
            "model": args.model,
            "strength": strength.value,
            "temperature": args.temperature,
            "selected_fields": selected_fields,
        },
        "results": results,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    log("📄", f"报告已保存: {report_path}")
    print()


async def batch_translate(args: argparse.Namespace):
    """Batch translate mode."""
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    target_lang = args.translate.strip().lower()
    if target_lang not in ("zh", "en", "ja"):
        print(f"{C.RED}  ✗ 不支持的目标语言: {target_lang}，请使用 zh / en / ja{C.RESET}")
        return

    lang_names = {"zh": "中文", "en": "English", "ja": "日本語"}

    files = sorted([
        f for f in input_dir.iterdir()
        if f.suffix.lower() in (".png", ".webp", ".charx", ".json")
        and not f.name.startswith(".")
    ])

    if not files:
        log("!", f"在 {input_dir} 中没有找到角色卡文件", C.YELLOW)
        return

    header(f"Card Wash 批量翻译 — {len(files)} 个文件 → {lang_names[target_lang]}")

    try:
        provider = LLMProvider(args.provider)
    except ValueError:
        provider = LLMProvider.OPENAI_COMPATIBLE

    config = LLMConfig(
        provider=provider,
        api_key=args.api_key,
        model=args.model,
        base_url=args.base_url,
        temperature=0.3,  # lower for translation
    )

    selected_fields = (
        [f.strip() for f in args.fields.split(",") if f.strip()]
        if args.fields
        else None
    )

    log("⚙", f"提供商: {provider.value}  模型: {args.model}", C.DIM)
    log("⚙", f"目标语言: {lang_names[target_lang]}", C.DIM)
    log("⚙", f"输出目录: {output_dir}", C.DIM)
    print()

    results = []
    total = len(files)
    t0 = time.time()

    for i, fp in enumerate(files, 1):
        prefix = f"[{i}/{total}]"

        # Check existing
        translated_json = output_dir / f"{fp.stem}_translated.json"
        translated_png = output_dir / f"{fp.stem}_translated.png"
        if not args.force and (translated_json.exists() or translated_png.exists()):
            log("→", f"{prefix} {C.DIM}{fp.name} — 已存在，跳过{C.RESET}")
            results.append({
                "file": fp.name, "status": "exists",
                "source_lang": "", "target_lang": target_lang,
                "fields_translated": 0, "error": "",
            })
            continue

        log("▶", f"{prefix} {fp.name} ...", C.BLUE)

        res = await translate_one(fp, output_dir, config, target_lang, selected_fields, args.format)
        results.append(res)

        src_name = lang_names.get(res.get("source_lang", ""), "?")
        if res["status"] == "ok":
            log("✓", f"{prefix} {fp.name}  {src_name} → {lang_names[target_lang]}  翻译 {res['fields_translated']} 个字段", C.GREEN)
        elif res["status"] == "skipped":
            log("○", f"{prefix} {fp.name}  已经是 {lang_names[target_lang]}，跳过", C.DIM)
        elif res["status"] == "error":
            log("✗", f"{prefix} {fp.name}  {C.RED}错误: {res['error']}{C.RESET}", C.RED)

        if i < total and res["status"] == "ok":
            await asyncio.sleep(args.delay)

    elapsed = time.time() - t0
    header("翻译完成")

    ok_count = sum(1 for r in results if r["status"] == "ok")
    skip_count = sum(1 for r in results if r["status"] in ("skipped", "exists"))
    err_count = sum(1 for r in results if r["status"] == "error")

    log("📊", f"总计: {total} 个文件")
    log("✓", f"成功翻译: {C.GREEN}{ok_count}{C.RESET}")
    log("○", f"跳过: {C.DIM}{skip_count}{C.RESET}")
    if err_count:
        log("✗", f"错误: {C.RED}{err_count}{C.RESET}")
    log("⏱", f"耗时: {elapsed:.1f}s")
    log("📁", f"输出目录: {output_dir}")
    print()


# ── CLI ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Card Wash — AI 角色卡批量清洗工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 使用 OpenAI 中度改写
  python3 batch.py ./cards/ -o ./washed/ \\
      --provider openai --api-key sk-xxx --model gpt-4o-mini

  # 使用 Ollama 本地模型
  python3 batch.py ./cards/ -o ./washed/ \\
      --provider openai_compatible --api-key none \\
      --base-url http://localhost:11434/v1 --model llama3

  # 仅改写指定字段，重度改写
  python3 batch.py ./cards/ -o ./washed/ \\
      --provider anthropic --api-key sk-ant-xxx \\
      --model claude-sonnet-4-20250514 --strength heavy \\
      --fields name,description,scenario,first_mes
        """,
    )
    parser.add_argument("input_dir", help="输入目录（含 .png / .json 角色卡）")
    parser.add_argument("-o", "--output-dir", default="./washed_output", help="输出目录 (默认: ./washed_output)")
    parser.add_argument("--provider", default="openai", choices=["openai", "anthropic", "openai_compatible"], help="LLM 提供商")
    parser.add_argument("--api-key", required=True, help="API Key")
    parser.add_argument("--model", default="gpt-4o-mini", help="模型名 (默认: gpt-4o-mini)")
    parser.add_argument("--base-url", default=None, help="自定义 API 端点 (用于 openai_compatible)")
    parser.add_argument("--strength", default="medium", choices=["light", "medium", "heavy"], help="改写强度 (默认: medium)")
    parser.add_argument("--fields", default="", help="逗号分隔的字段列表，留空=全部")
    parser.add_argument("--temperature", type=float, default=0.7, help="LLM temperature (默认: 0.7)")
    parser.add_argument("--format", default="same", choices=["same", "png", "json"], help="输出格式: same=保持原格式, png, json (默认: same)")
    parser.add_argument("--delay", type=float, default=1.0, help="每个文件之间的延迟秒数 (默认: 1.0)")
    parser.add_argument("--force", action="store_true", help="强制覆盖已存在的输出文件")
    parser.add_argument("--force-rewrite", action="store_true", help="强制清洗所有卡（即使风险评分为 0）")
    parser.add_argument("--translate", default="", metavar="LANG", help="翻译模式: 目标语言 zh/en/ja (例: --translate en)")

    args = parser.parse_args()

    if args.format == "same":
        args.format = "png"  # default to png, will auto-detect per file

    if args.translate:
        asyncio.run(batch_translate(args))
    else:
        asyncio.run(batch_process(args))


if __name__ == "__main__":
    main()
