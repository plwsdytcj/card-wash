"""
Copyright risk analyser for character card fields.

Scans text fields for known IP names, franchise references, and other
copyright indicators.  Produces a per-field risk score (0-5) and highlights
the matching fragments so the user can see *exactly* what triggered the flag.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from models import CharacterCard


# ═══════════════════════════════════════════════════════════════════════════════
#  Keyword database (extensible)
# ═══════════════════════════════════════════════════════════════════════════════

# Each entry: (pattern, weight, category)
# pattern  – regex (case-insensitive)
# weight   – how strongly this indicates copyright (1-5)
# category – human-readable bucket

_RAW_RULES: list[tuple[str, int, str]] = [
    # ══════════════════════════════════════════════════════════════════
    #  English rules
    # ══════════════════════════════════════════════════════════════════

    # ── Anime / Manga ─────────────────────────────────────────────────
    (r"\bNaruto\b", 4, "anime"),
    (r"\bSasuke\b", 4, "anime"),
    (r"\bKonoha\b", 3, "anime"),
    (r"\bChakra\b", 2, "anime"),
    (r"\bOne\s*Piece\b", 4, "anime"),
    (r"\bLuffy\b", 4, "anime"),
    (r"\bStraw\s*Hat\b", 3, "anime"),
    (r"\bDragon\s*Ball\b", 4, "anime"),
    (r"\bGoku\b", 4, "anime"),
    (r"\bVegeta\b", 4, "anime"),
    (r"\bSaiyan\b", 3, "anime"),
    (r"\bKamehameha\b", 3, "anime"),
    (r"\bAttack\s*on\s*Titan\b", 4, "anime"),
    (r"\bEren\s*Yeager\b", 4, "anime"),
    (r"\bSurvey\s*Corps\b", 3, "anime"),
    (r"\bDemon\s*Slayer\b", 4, "anime"),
    (r"\bTanjiro\b", 4, "anime"),
    (r"\bNezuko\b", 4, "anime"),
    (r"\bJujutsu\s*Kaisen\b", 4, "anime"),
    (r"\bGojo\b", 4, "anime"),
    (r"\bSukuna\b", 3, "anime"),
    (r"\bMy\s*Hero\s*Academia\b", 4, "anime"),
    (r"\bDeku\b", 3, "anime"),
    (r"\bAll\s*Might\b", 3, "anime"),
    (r"\bSword\s*Art\s*Online\b", 4, "anime"),
    (r"\bKirito\b", 4, "anime"),
    (r"\bAsuna\b", 3, "anime"),
    (r"\bRe:\s*Zero\b", 4, "anime"),
    (r"\bSubaru\s*Natsuki\b", 4, "anime"),
    (r"\bRem\b(?=.*\b(?:Ram|Emilia|Roswaal)\b)", 3, "anime"),
    (r"\bEmilia\b(?=.*\b(?:Rem|Subaru|Puck)\b)", 3, "anime"),
    (r"\bNeon\s*Genesis\s*Evangelion\b", 4, "anime"),
    (r"\bShinji\b", 3, "anime"),
    (r"\bRei\s*Ayanami\b", 4, "anime"),
    (r"\bAsuka\s*Langley\b", 4, "anime"),
    (r"\bSailor\s*Moon\b", 4, "anime"),
    (r"\bHatsune\s*Miku\b", 4, "vocaloid"),
    (r"\bVocaloid\b", 3, "vocaloid"),
    (r"\bFate[/\s]*(?:Stay|Grand|Zero|Apocrypha)\b", 4, "anime"),
    (r"\bSaber\b(?=.*\b(?:Fate|Servant|Excalibur)\b)", 3, "anime"),
    (r"\bServant\b(?=.*\b(?:Fate|Master|Holy\s*Grail)\b)", 2, "anime"),
    (r"\bTokyo\s*Ghoul\b", 4, "anime"),
    (r"\bKaneki\b", 4, "anime"),
    (r"\bDeath\s*Note\b", 4, "anime"),
    (r"\bLight\s*Yagami\b", 4, "anime"),
    (r"\bFullmetal\s*Alchemist\b", 4, "anime"),
    (r"\bEdward\s*Elric\b", 4, "anime"),
    (r"\bBleach\b(?=.*\b(?:Soul|Shinigami|Zanpakuto|Hollow)\b)", 3, "anime"),
    (r"\bIchigo\s*Kurosaki\b", 4, "anime"),
    (r"\bShinigami\b", 2, "anime"),
    (r"\bHunter\s*x\s*Hunter\b", 4, "anime"),
    (r"\bGon\s*Freecss\b", 4, "anime"),
    (r"\bKillua\b", 3, "anime"),
    (r"\bSpy\s*x\s*Family\b", 4, "anime"),
    (r"\bAnya\s*Forger\b", 4, "anime"),
    (r"\bChainsaw\s*Man\b", 4, "anime"),
    (r"\bDenji\b", 3, "anime"),
    (r"\bMakima\b", 3, "anime"),
    (r"\bFrieren\b", 3, "anime"),
    (r"\bBocchi\b(?=.*\b(?:Rock|band)\b)", 3, "anime"),
    (r"\bKaguya[- ]sama\b", 4, "anime"),
    (r"\bOshino\s*Meme\b", 3, "anime"),

    # ── Games (English) ───────────────────────────────────────────────
    (r"\bGenshin\s*Impact\b", 4, "game"),
    (r"\bTeyvat\b", 3, "game"),
    (r"\bMondstadt\b", 3, "game"),
    (r"\bLiyue\b", 3, "game"),
    (r"\bInazuma\b(?=.*\b(?:Genshin|Vision|Archon|Sumeru)\b)", 3, "game"),
    (r"\bSumeru\b", 3, "game"),
    (r"\bFontaine\b(?=.*\b(?:Genshin|Archon|Hydro|Furina)\b)", 3, "game"),
    (r"\bNatlan\b", 3, "game"),
    (r"\bSnezhnaya\b", 3, "game"),
    (r"\bHonkai\s*(?:Star\s*Rail|Impact)\b", 4, "game"),
    (r"\bZenless\s*Zone\s*Zero\b", 4, "game"),
    (r"\bArknights\b", 4, "game"),
    (r"\bAzur\s*Lane\b", 4, "game"),
    (r"\bBlue\s*Archive\b", 4, "game"),
    (r"\bGirls['']?\s*Frontline\b", 4, "game"),
    (r"\bFire\s*Emblem\b", 4, "game"),
    (r"\bPersona\s*[345]\b", 4, "game"),
    (r"\bFinal\s*Fantasy\b", 4, "game"),
    (r"\bZelda\b", 4, "game"),
    (r"\bHyrule\b", 3, "game"),
    (r"\bPokemon\b|Pokémon", 4, "game"),
    (r"\bPikachu\b", 4, "game"),
    (r"\bLeague\s*of\s*Legends\b", 4, "game"),
    (r"\bValorant\b", 3, "game"),
    (r"\bOverwatch\b", 4, "game"),
    (r"\bMinecraft\b", 3, "game"),
    (r"\bElden\s*Ring\b", 4, "game"),
    (r"\bDark\s*Souls\b", 4, "game"),
    (r"\bBaldur['']?s\s*Gate\b", 4, "game"),
    (r"\bNieR\b", 3, "game"),
    (r"\b2B\b(?=.*\b(?:NieR|YoRHa|Android|9S)\b)", 3, "game"),
    (r"\bYoRHa\b", 3, "game"),
    (r"\bWuthering\s*Waves\b", 4, "game"),
    (r"\bNikke\b", 3, "game"),
    (r"\bLimbus\s*Company\b", 4, "game"),
    (r"\bProject\s*Moon\b", 3, "game"),
    (r"\bGenshin\b", 3, "game"),

    # ── Film / TV / Western ───────────────────────────────────────────
    (r"\bHarry\s*Potter\b", 5, "film"),
    (r"\bHogwarts\b", 4, "film"),
    (r"\bDumbledore\b", 4, "film"),
    (r"\bVoldemort\b", 4, "film"),
    (r"\bStar\s*Wars\b", 5, "film"),
    (r"\bJedi\b", 3, "film"),
    (r"\bSith\b", 3, "film"),
    (r"\bMarvel\b", 4, "film"),
    (r"\bAvengers\b", 4, "film"),
    (r"\bSpider[- ]?Man\b", 4, "film"),
    (r"\bIron\s*Man\b", 4, "film"),
    (r"\bDC\s*Comics\b", 4, "film"),
    (r"\bBatman\b", 4, "film"),
    (r"\bSuperman\b", 4, "film"),
    (r"\bGotham\b(?=.*\b(?:Batman|Wayne|Joker)\b)", 3, "film"),
    (r"\bLord\s*of\s*the\s*Rings\b", 5, "film"),
    (r"\bMiddle[- ]?Earth\b", 3, "film"),
    (r"\bGandalf\b", 4, "film"),
    (r"\bFrodo\b", 4, "film"),
    (r"\bGame\s*of\s*Thrones\b", 4, "film"),
    (r"\bWesteros\b", 3, "film"),
    (r"\bTargaryen\b", 3, "film"),
    (r"\bLannister\b", 3, "film"),
    (r"\bDisney\b", 4, "film"),
    (r"\bPixar\b", 3, "film"),
    (r"\bFrozen\b(?=.*\b(?:Elsa|Anna|Arendelle)\b)", 3, "film"),
    (r"\bTransformers\b", 4, "film"),
    (r"\bTerminator\b", 4, "film"),
    (r"\bJohn\s*Wick\b", 3, "film"),
    (r"\bSherlock\s*Holmes\b", 2, "film"),  # public domain, low weight

    # ── Visual Novels / Light Novels ──────────────────────────────────
    (r"\bDoki\s*Doki\b", 3, "vn"),
    (r"\bMonika\b(?=.*\b(?:Doki|DDLC|literature)\b)", 3, "vn"),
    (r"\bClannad\b", 3, "vn"),
    (r"\bSteins[;]?\s*Gate\b", 4, "vn"),
    (r"\bDanganronpa\b", 4, "vn"),

    # ══════════════════════════════════════════════════════════════════
    #  日本語 (Japanese)
    # ══════════════════════════════════════════════════════════════════
    ("ナルト", 4, "anime"),
    ("うずまきナルト", 4, "anime"),
    ("うちはサスケ", 4, "anime"),
    ("木ノ葉", 3, "anime"),
    ("ワンピース", 4, "anime"),
    ("ルフィ", 4, "anime"),
    ("麦わらの一味", 3, "anime"),
    ("ドラゴンボール", 4, "anime"),
    ("悟空", 4, "anime"),
    ("ベジータ", 4, "anime"),
    ("サイヤ人", 3, "anime"),
    ("かめはめ波", 3, "anime"),
    ("進撃の巨人", 4, "anime"),
    ("エレン・イェーガー", 4, "anime"),
    ("調査兵団", 3, "anime"),
    ("鬼滅の刃", 4, "anime"),
    ("竈門炭治郎", 4, "anime"),
    ("竈門禰豆子", 4, "anime"),
    ("呪術廻戦", 4, "anime"),
    ("五条悟", 4, "anime"),
    ("両面宿儺", 3, "anime"),
    ("僕のヒーローアカデミア", 4, "anime"),
    ("ソードアート・オンライン", 4, "anime"),
    ("キリト", 4, "anime"),
    ("リゼロ", 3, "anime"),
    ("ナツキ・スバル", 4, "anime"),
    ("レム(?=.*(?:ラム|エミリア|ロズワール))", 3, "anime"),
    ("エヴァンゲリオン", 4, "anime"),
    ("碇シンジ", 4, "anime"),
    ("綾波レイ", 4, "anime"),
    ("惣流・アスカ", 4, "anime"),
    ("セーラームーン", 4, "anime"),
    ("初音ミク", 4, "vocaloid"),
    ("ボーカロイド", 3, "vocaloid"),
    ("Fate/(?:stay|Grand|Zero)", 4, "anime"),
    ("東京喰種", 4, "anime"),
    ("金木研", 4, "anime"),
    ("デスノート", 4, "anime"),
    ("夜神月", 4, "anime"),
    ("鋼の錬金術師", 4, "anime"),
    ("エドワード・エルリック", 4, "anime"),
    ("ブリーチ", 3, "anime"),
    ("黒崎一護", 4, "anime"),
    ("死神", 2, "anime"),
    ("ハンター×ハンター", 4, "anime"),
    ("ゴン・フリークス", 4, "anime"),
    ("キルア", 3, "anime"),
    ("スパイファミリー", 4, "anime"),
    ("アーニャ・フォージャー", 4, "anime"),
    ("チェンソーマン", 4, "anime"),
    ("デンジ", 3, "anime"),
    ("マキマ", 3, "anime"),
    ("フリーレン", 3, "anime"),
    ("葬送のフリーレン", 4, "anime"),
    ("ぼっち・ざ・ろっく", 4, "anime"),
    ("かぐや様", 4, "anime"),
    ("ダンガンロンパ", 4, "vn"),
    ("シュタインズ・ゲート", 4, "vn"),
    # Japanese game titles
    ("原神", 4, "game"),
    ("テイワット", 3, "game"),
    ("モンド", 3, "game"),
    ("璃月", 3, "game"),
    ("稲妻", 3, "game"),
    ("スメール", 3, "game"),
    ("フォンテーヌ", 3, "game"),
    ("崩壊スターレイル", 4, "game"),
    ("崩壊3rd", 4, "game"),
    ("ゼンレスゾーンゼロ", 4, "game"),
    ("アークナイツ", 4, "game"),
    ("アズールレーン", 4, "game"),
    ("ブルーアーカイブ", 4, "game"),
    ("ドールズフロントライン", 4, "game"),
    ("ファイアーエムブレム", 4, "game"),
    ("ペルソナ[345]", 4, "game"),
    ("ファイナルファンタジー", 4, "game"),
    ("ゼルダの伝説", 4, "game"),
    ("ハイラル", 3, "game"),
    ("ポケモン|ポケットモンスター", 4, "game"),
    ("ピカチュウ", 4, "game"),
    ("ニーア", 3, "game"),
    ("エルデンリング", 4, "game"),
    ("ダークソウル", 4, "game"),
    ("鳴潮", 4, "game"),
    # Japanese film/media
    ("ハリー・ポッター", 5, "film"),
    ("ホグワーツ", 4, "film"),
    ("スター・ウォーズ", 5, "film"),
    ("ジェダイ", 3, "film"),
    ("マーベル", 4, "film"),
    ("アベンジャーズ", 4, "film"),
    ("スパイダーマン", 4, "film"),
    ("バットマン", 4, "film"),
    ("スーパーマン", 4, "film"),
    ("ロード・オブ・ザ・リング", 5, "film"),
    ("ゲーム・オブ・スローンズ", 4, "film"),
    ("ディズニー", 4, "film"),

    # ══════════════════════════════════════════════════════════════════
    #  中文 (Chinese)
    # ══════════════════════════════════════════════════════════════════
    ("火影忍者", 4, "anime"),
    ("漩涡鸣人", 4, "anime"),
    ("宇智波佐助", 4, "anime"),
    ("木叶村|木叶忍者村", 3, "anime"),
    ("海贼王", 4, "anime"),
    ("路飞", 4, "anime"),
    ("草帽海贼团", 3, "anime"),
    ("龙珠", 4, "anime"),
    ("悟空", 4, "anime"),
    ("贝吉塔", 4, "anime"),
    ("赛亚人", 3, "anime"),
    ("龟派气功", 3, "anime"),
    ("进击的巨人", 4, "anime"),
    ("艾伦·耶格尔|艾伦·耶格", 4, "anime"),
    ("调查兵团", 3, "anime"),
    ("鬼灭之刃", 4, "anime"),
    ("灶门炭治郎", 4, "anime"),
    ("灶门祢豆子", 4, "anime"),
    ("咒术回战", 4, "anime"),
    ("五条悟", 4, "anime"),
    ("两面宿傩", 3, "anime"),
    ("我的英雄学院", 4, "anime"),
    ("刀剑神域", 4, "anime"),
    ("桐人", 4, "anime"),
    ("从零开始的异世界生活", 4, "anime"),
    ("菜月昴", 4, "anime"),
    ("蕾姆(?=.*(?:拉姆|爱蜜莉雅))", 3, "anime"),
    ("新世纪福音战士|EVA(?=.*(?:使徒|AT力场|绫波))", 4, "anime"),
    ("碇真嗣", 4, "anime"),
    ("绫波丽", 4, "anime"),
    ("明日香", 3, "anime"),
    ("美少女战士", 4, "anime"),
    ("初音未来|初音ミク", 4, "vocaloid"),
    ("东京喰种|东京食尸鬼", 4, "anime"),
    ("金木研", 4, "anime"),
    ("死亡笔记", 4, "anime"),
    ("夜神月", 4, "anime"),
    ("钢之炼金术师", 4, "anime"),
    ("爱德华·艾尔利克", 4, "anime"),
    ("死神(?=.*(?:灵压|斩魄刀|虚|尸魂界))", 3, "anime"),
    ("黑崎一护", 4, "anime"),
    ("全职猎人", 4, "anime"),
    ("小杰·富力士", 4, "anime"),
    ("奇犽", 3, "anime"),
    ("间谍过家家", 4, "anime"),
    ("阿尼亚·福杰", 4, "anime"),
    ("电锯人", 4, "anime"),
    ("玛奇玛", 3, "anime"),
    ("葬送的芙莉莲", 4, "anime"),
    ("孤独摇滚", 4, "anime"),
    ("辉夜大小姐", 4, "anime"),
    ("弹丸论破", 4, "vn"),
    ("命运之夜|Fate/(?:stay|Grand|Zero)", 4, "anime"),
    # Chinese game titles
    ("原神", 4, "game"),
    ("提瓦特", 3, "game"),
    ("蒙德", 3, "game"),
    ("璃月", 3, "game"),
    ("稻妻", 3, "game"),
    ("须弥", 3, "game"),
    ("枫丹", 3, "game"),
    ("纳塔", 3, "game"),
    ("至冬", 3, "game"),
    ("崩坏星穹铁道", 4, "game"),
    ("崩坏三|崩坏3", 4, "game"),
    ("绝区零", 4, "game"),
    ("明日方舟", 4, "game"),
    ("碧蓝航线", 4, "game"),
    ("蔚蓝档案", 4, "game"),
    ("少女前线", 4, "game"),
    ("火焰纹章|火焰之纹章", 4, "game"),
    ("女神异闻录[345]", 4, "game"),
    ("最终幻想", 4, "game"),
    ("塞尔达传说", 4, "game"),
    ("海拉鲁", 3, "game"),
    ("宝可梦|精灵宝可梦|神奇宝贝", 4, "game"),
    ("皮卡丘", 4, "game"),
    ("英雄联盟", 4, "game"),
    ("无畏契约", 3, "game"),
    ("守望先锋", 4, "game"),
    ("我的世界", 3, "game"),
    ("艾尔登法环", 4, "game"),
    ("黑暗之魂", 4, "game"),
    ("博德之门", 4, "game"),
    ("尼尔", 3, "game"),
    ("鸣潮", 4, "game"),
    ("胜利女神：妮姬|胜利女神", 3, "game"),
    ("边狱公司", 4, "game"),
    # Chinese film/media
    ("哈利·波特|哈利波特", 5, "film"),
    ("霍格沃茨", 4, "film"),
    ("邓布利多", 4, "film"),
    ("伏地魔", 4, "film"),
    ("星球大战", 5, "film"),
    ("绝地武士", 3, "film"),
    ("西斯", 3, "film"),
    ("漫威", 4, "film"),
    ("复仇者联盟", 4, "film"),
    ("蜘蛛侠", 4, "film"),
    ("钢铁侠", 4, "film"),
    ("蝙蝠侠", 4, "film"),
    ("超人", 3, "film"),
    ("指环王|魔戒", 5, "film"),
    ("甘道夫", 4, "film"),
    ("权力的游戏", 4, "film"),
    ("维斯特洛", 3, "film"),
    ("坦格利安", 3, "film"),
    ("迪士尼", 4, "film"),
    ("冰雪奇缘", 4, "film"),
    ("变形金刚", 4, "film"),
    ("终结者", 4, "film"),

    # ══════════════════════════════════════════════════════════════════
    #  한국어 (Korean)
    # ══════════════════════════════════════════════════════════════════
    ("나루토", 4, "anime"),
    ("원피스", 4, "anime"),
    ("루피", 4, "anime"),
    ("드래곤볼", 4, "anime"),
    ("진격의 거인", 4, "anime"),
    ("귀멸의 칼날", 4, "anime"),
    ("주술회전", 4, "anime"),
    ("고죠 사토루", 4, "anime"),
    ("나의 히어로 아카데미아", 4, "anime"),
    ("소드 아트 온라인", 4, "anime"),
    ("리제로", 3, "anime"),
    ("에반게리온", 4, "anime"),
    ("세일러문", 4, "anime"),
    ("하츠네 미쿠", 4, "vocaloid"),
    ("체인소맨", 4, "anime"),
    ("프리렌", 3, "anime"),
    ("장송의 프리렌", 4, "anime"),
    ("스파이 패밀리", 4, "anime"),
    # Korean game titles
    ("원신", 4, "game"),
    ("티바트", 3, "game"),
    ("붕괴 스타레일", 4, "game"),
    ("젠레스 존 제로", 4, "game"),
    ("명일방주", 4, "game"),
    ("벽람항로", 4, "game"),
    ("블루 아카이브", 4, "game"),
    ("소녀전선", 4, "game"),
    ("파이어 엠블렘", 4, "game"),
    ("페르소나[345]", 4, "game"),
    ("파이널 판타지", 4, "game"),
    ("젤다의 전설", 4, "game"),
    ("포켓몬", 4, "game"),
    ("피카츄", 4, "game"),
    ("리그 오브 레전드", 4, "game"),
    ("오버워치", 4, "game"),
    ("엘든 링", 4, "game"),
    ("니어", 3, "game"),
    ("명조", 4, "game"),
    # Korean film/media
    ("해리 포터", 5, "film"),
    ("호그와트", 4, "film"),
    ("스타워즈", 5, "film"),
    ("마블", 4, "film"),
    ("어벤져스", 4, "film"),
    ("스파이더맨", 4, "film"),
    ("배트맨", 4, "film"),
    ("반지의 제왕", 5, "film"),
    ("왕좌의 게임", 4, "film"),
    ("디즈니", 4, "film"),

    # ══════════════════════════════════════════════════════════════════
    #  Generic copyright signals (all languages)
    # ══════════════════════════════════════════════════════════════════
    (r"©", 3, "meta"),
    (r"\bAll\s*Rights\s*Reserved\b", 3, "meta"),
    (r"\bTrademark\b", 2, "meta"),
    (r"\b™\b", 3, "meta"),
    (r"\b®\b", 3, "meta"),
    ("版权所有", 3, "meta"),
    ("著作権", 3, "meta"),
]

# Pre-compile
_COMPILED_RULES: list[tuple[re.Pattern, int, str]] = [
    (re.compile(pat, re.IGNORECASE), w, cat) for pat, w, cat in _RAW_RULES
]


# ═══════════════════════════════════════════════════════════════════════════════
#  Analysis result types
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class Match:
    text: str
    start: int
    end: int
    weight: int
    category: str


@dataclass
class FieldAnalysis:
    field_name: str
    risk_score: int = 0  # 0-5
    matches: list[Match] = field(default_factory=list)


@dataclass
class CardAnalysis:
    overall_risk: int = 0  # 0-5
    fields: list[FieldAnalysis] = field(default_factory=list)
    summary: str = ""
    detected_language: str = "en"  # "en", "zh", "ja", "ko", "mixed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_risk": self.overall_risk,
            "summary": self.summary,
            "detected_language": self.detected_language,
            "fields": [
                {
                    "field_name": f.field_name,
                    "risk_score": f.risk_score,
                    "matches": [
                        {
                            "text": m.text,
                            "start": m.start,
                            "end": m.end,
                            "weight": m.weight,
                            "category": m.category,
                        }
                        for m in f.matches
                    ],
                }
                for f in self.fields
            ],
        }


# ═══════════════════════════════════════════════════════════════════════════════
#  Core analysis logic
# ═══════════════════════════════════════════════════════════════════════════════


def _analyse_text(text: str) -> list[Match]:
    """Run all rules against *text* and return de-duplicated matches."""
    matches: list[Match] = []
    seen: set[tuple[int, int]] = set()
    for pattern, weight, category in _COMPILED_RULES:
        for m in pattern.finditer(text):
            key = (m.start(), m.end())
            if key not in seen:
                seen.add(key)
                matches.append(
                    Match(
                        text=m.group(),
                        start=m.start(),
                        end=m.end(),
                        weight=weight,
                        category=category,
                    )
                )
    matches.sort(key=lambda x: x.start)
    return matches


def _score_from_matches(matches: list[Match]) -> int:
    """Compute a 0-5 risk score from a list of matches."""
    if not matches:
        return 0
    max_weight = max(m.weight for m in matches)
    density_bonus = min(len(matches) // 3, 2)  # many hits raise the score
    return min(max_weight + density_bonus, 5)


def detect_language(text: str) -> str:
    """
    Detect the primary language of *text* by character-class heuristics.

    Returns one of: ``"ja"``, ``"zh"``, ``"ko"``, ``"en"``, ``"mixed"``.
    """
    if not text:
        return "en"

    # Count characters in each script
    cjk = 0       # Shared CJK ideographs (Chinese / Japanese kanji)
    hiragana = 0   # Japanese
    katakana = 0   # Japanese
    hangul = 0     # Korean
    latin = 0      # English / romanised

    for ch in text:
        cp = ord(ch)
        if 0x3040 <= cp <= 0x309F:
            hiragana += 1
        elif 0x30A0 <= cp <= 0x30FF:
            katakana += 1
        elif 0xAC00 <= cp <= 0xD7AF or 0x1100 <= cp <= 0x11FF:
            hangul += 1
        elif (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF
              or 0x20000 <= cp <= 0x2A6DF):
            cjk += 1
        elif 0x0041 <= cp <= 0x007A:
            latin += 1

    total_script = cjk + hiragana + katakana + hangul + latin
    if total_script == 0:
        return "en"

    jp_chars = hiragana + katakana
    # Japanese: has hiragana/katakana (unique to JP)
    if jp_chars > 0 and jp_chars / total_script > 0.05:
        return "ja"
    # Korean: has hangul
    if hangul > 0 and hangul / total_script > 0.05:
        return "ko"
    # Chinese: has CJK but no JP/KR script markers
    if cjk > 0 and cjk / total_script > 0.1:
        return "zh"
    # Predominantly Latin
    if latin / total_script > 0.6:
        return "en"
    # Mixed
    return "mixed"


def analyse_card(card: CharacterCard) -> CardAnalysis:
    """Analyse all rewritable fields of *card* for copyright risk."""
    field_results: list[FieldAnalysis] = []
    all_matches: list[Match] = []

    # Detect language from the two most content-rich fields
    lang_sample = " ".join(
        v for k, v in card.get_rewritable_fields().items()
        if k in ("description", "personality", "scenario", "first_mes")
    )
    detected_lang = detect_language(lang_sample)

    for fname, fval in card.get_rewritable_fields().items():
        matches = _analyse_text(fval)
        score = _score_from_matches(matches)
        field_results.append(
            FieldAnalysis(field_name=fname, risk_score=score, matches=matches)
        )
        all_matches.extend(matches)

    # Also scan lorebook entries
    if card.data.character_book:
        for entry in card.data.character_book.entries:
            matches = _analyse_text(entry.content)
            score = _score_from_matches(matches)
            fname = f"lorebook:{entry.name or entry.id}"
            field_results.append(
                FieldAnalysis(field_name=fname, risk_score=score, matches=matches)
            )
            all_matches.extend(matches)

    # Also scan alternate greetings
    for idx, greeting in enumerate(card.data.alternate_greetings):
        matches = _analyse_text(greeting)
        score = _score_from_matches(matches)
        field_results.append(
            FieldAnalysis(
                field_name=f"alternate_greetings[{idx}]",
                risk_score=score,
                matches=matches,
            )
        )
        all_matches.extend(matches)

    overall = _score_from_matches(all_matches)

    # Build summary (localised)
    categories = set(m.category for m in all_matches)
    ip_names = list(dict.fromkeys(m.text for m in all_matches))[:10]

    _LANG_LABELS = {"en": "English", "zh": "中文", "ja": "日本語", "ko": "한국어", "mixed": "Mixed"}
    lang_label = _LANG_LABELS.get(detected_lang, detected_lang)

    if all_matches:
        if detected_lang == "zh":
            summary = (
                f"检测到 {len(all_matches)} 个版权指标，"
                f"涉及类别: {', '.join(sorted(categories))}。"
                f"关键词: {', '.join(ip_names)}。"
                f"卡片语言: {lang_label}"
            )
        elif detected_lang == "ja":
            summary = (
                f"{len(all_matches)} 件の著作権指標を検出。"
                f"カテゴリ: {', '.join(sorted(categories))}。"
                f"キーワード: {', '.join(ip_names)}。"
                f"カード言語: {lang_label}"
            )
        else:
            summary = (
                f"Detected {len(all_matches)} copyright indicator(s) "
                f"across categories: {', '.join(sorted(categories))}. "
                f"Key terms: {', '.join(ip_names)}. "
                f"Card language: {lang_label}"
            )
    else:
        if detected_lang == "zh":
            summary = f"未检测到明显的版权指标。卡片语言: {lang_label}"
        elif detected_lang == "ja":
            summary = f"明らかな著作権指標は検出されませんでした。カード言語: {lang_label}"
        else:
            summary = f"No obvious copyright indicators detected. Card language: {lang_label}"

    return CardAnalysis(
        overall_risk=overall,
        fields=field_results,
        summary=summary,
        detected_language=detected_lang,
    )
