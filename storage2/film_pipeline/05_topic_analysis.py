# -*- coding: utf-8 -*-
"""
05_topic_analysis.py
主题分析：多标签主题标注 + 四类统计 + 图表 + 代表评论候选表

输入（唯一）：
    04_sentiment_final.csv       情感分析已冻结的最终数据（1195 条 × 38 列）

用法：
    python 05_topic_analysis.py --smoke    # 100 条冒烟，产出 05_smoke_report.xlsx，供确认主题体系
    python 05_topic_analysis.py            # 全量，产出 05_topic_labeled.csv / topic_summary.xlsx / 4 PNG / representative_comments.xlsx
    python 05_topic_analysis.py --full     # 同全量

核心设计（对照需求）：
    - 多标签：一条评论可命中多个主题（需求2）
    - 排除 sentiment_final=other 做统计，other 保留审计（需求1）
    - 宽泛英文词(release/platform/game/popular/character/ending/battle/slow等)
      用 强词w/短语p/共现c 三种模式防误判（需求点3）
    - topic_unmatched=True 仅表示"未被当前中英词库识别"，不是无主题（需求点6）
    - score 只在平台内部比较；AniList 的 score 是评分非互动量，改用信息量/主题覆盖/
      评分极端性/完整度筛选（需求点4、6）
"""

import sys
import argparse
import re
import random
from collections import defaultdict
from difflib import SequenceMatcher

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

sys.stdout.reconfigure(encoding="utf-8")

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial"]
plt.rcParams["axes.unicode_minus"] = False

# ---------------------------------------------------------------------------
# 0. 常量
# ---------------------------------------------------------------------------
INPUT = "04_sentiment_final.csv"   # 默认输入；--input 可覆盖
SENT_ORDER = ["positive", "neutral", "mixed", "negative"]
SENT_ZH = {"positive": "正面", "neutral": "中性", "mixed": "混合", "negative": "负面", "other": "其他"}
# 其他语言 = 不属于 {英语, 中文, 中英混合} 的语言组（中英词库最可能覆盖不到）
CORE_LANGS = {"英语", "中文", "中英混合"}

# 平台按 score 语义分两类（代表评论筛选用）：
#   评分型平台：score 是「评分」（AniList 0-100 / MAL 0-10 / RT 0.5-5 星），不是互动量
#   互动型平台：score 是「互动量」（Reddit karma / YouTube·X 点赞）
RATING_PLATFORMS = {"AniList", "MAL", "RT"}
INTERACTION_PLATFORMS = {"Reddit", "YouTube", "X"}

# 输出文件名前缀（--prefix 传入，如 series_ / film_）
PREFIX = ""

# ---------------------------------------------------------------------------
# 1. 主题体系：12 个主题，多语言关键词，三种匹配模式
#    每种语言一个块：w=强词直接命中 / p=短语整体匹配 / c=共现（词+co词同时出现）
#    外语词库与中英分开维护，命中词加语言前缀（es:/id:/ja:）便于审计（需求点7）
#    ja 仅音乐词，且只对日语语言组匹配（需求点6）
#    episode 不作独立关键词，仅作 co 触发词（需求点5）
# ---------------------------------------------------------------------------
# 语言块元信息：(代码, 前缀, 是否仅日语组)
LANG_BLOCKS = [
    ("en", "", False),
    ("zh", "", False),
    ("es", "es:", False),
    ("id", "id:", False),
    ("ja", "ja:", True),
]
JA_LANG = "日语"   # lang_group 里日语组的取值

TOPIC_LEXICON = {
    "story_plot": {
        "zh_label": "剧情与叙事", "en_label": "Plot & Story",
        "en": {
            "w": ["plot", "story", "storyline", "narrative", "storytelling", "subplot",
                  "premise", "writing", "screenplay", "arc", "cliffhanger", "finale",
                  "boring", "bland", "mediocre"],
            "p": ["story writing", "well written", "well-written", "poorly written", "story telling"],
            "c": {"ending": ["story", "plot", "narrative", "sad", "happy", "rushed",
                             "episode", "season", "finale", "剧情", "结局", "结尾"]},
        },
        "zh": {"w": ["剧情", "故事", "情节", "结局", "结尾", "叙事", "编剧", "主线", "支线", "故事线"], "c": {}},
        "es": {"w": ["trama"], "p": [],
               "c": {"historia": ["trama", "personajes", "serie", "episodio", "animación",
                                  "anime", "donghua", "protagonista", "final"]}},
        "id": {"w": [], "p": ["alur cerita", "jalan cerita"],
               "c": {"cerita": ["alur", "jalan", "grafis", "animasi", "donghua", "anime",
                                "episode", "keren", "bagus"]}},
    },
    "worldbuilding": {
        "zh_label": "世界观与设定", "en_label": "World-building",
        "en": {
            "w": ["worldbuilding", "lore", "cultivation", "realm", "sect", "mythology",
                  "universe", "setting", "magic system", "power system"],
            "p": ["world building", "power system", "nascent soul", "core formation"],
            "c": {},
        },
        "zh": {"w": ["世界观", "设定", "修炼", "修仙", "境界", "宗门", "体系", "力量体系", "修真",
                     "世界观设定", "功法", "金丹", "元婴", "筑基", "渡劫", "法术", "心法", "练气", "结婴",
                     "怪兽", "怪物"], "c": {}},
    },
    "character": {
        "zh_label": "角色塑造", "en_label": "Character",
        "en": {
            "w": ["protagonist", "villain", "antagonist", "hero", "heroine", "cast",
                  "personality", "characterization", "sidekick", "mc"],
            "p": ["character development", "character design", "character writing",
                  "main character", "side character", "character growth", "character arc",
                  "kill off", "character death"],
            "c": {"character": ["development", "design", "writing", "growth", "arc",
                                "protagonist", "villain", "hero", "cast", "personality", "mc",
                                "die", "death", "kill",
                                "主角", "反派", "塑造", "人设", "人物", "配角", "性格", "成长"]},
        },
        "zh": {"w": ["角色", "人物", "主角", "反派", "配角", "塑造", "人设", "性格", "成长", "角色塑造"],
               "c": {"邪恶": ["她", "他", "角色", "人", "女", "男"]}},
        "es": {"w": ["protagonista", "personajes", "villano"], "p": [], "c": {}},
    },
    "animation_visual": {
        "zh_label": "画面与动画制作", "en_label": "Visuals & Animation",
        "en": {
            "w": ["animation", "visual", "visuals", "cgi", "cg", "artwork", "graphics",
                  "rendering", "art direction", "animation quality"],
            "p": ["art style", "visual quality", "visual effects", "animation quality", "art direction",
                  "picture perfect", "gorgeous animation", "stunning animation", "beautiful animation"],
            "c": {"art": ["style", "direction", "work", "design", "beautiful", "gorgeous", "nice", "great"]},
        },
        "zh": {"w": ["画面", "动画", "画质", "画风", "美术", "视觉", "特效", "场景", "建模", "渲染", "帧率"], "c": {}},
        "es": {"w": ["animación", "animacion", "gráficos", "graficos"], "p": [], "c": {}},
        "id": {"w": ["grafis", "animasi"], "p": [], "c": {}},
    },
    "action_fight": {
        "zh_label": "动作与战斗场面", "en_label": "Action & Combat",
        "en": {
            "w": ["combat", "choreography", "action scene", "battle sequence", "fight choreography"],
            "p": ["fight scene", "fight scenes", "battle scene", "battle scenes",
                  "action scene", "action scenes", "fight choreography"],
            "c": {"fight": ["scene", "scenes", "choreography", "animation", "sequence",
                            "cool", "amazing", "epic", "打斗", "战斗"],
                  "battle": ["scene", "scenes", "sequence", "choreography", "animation", "打斗", "战斗"],
                  "action": ["scene", "scenes", "sequence", "choreography", "fight", "animation"]},
        },
        "zh": {"w": ["打斗", "战斗", "打戏", "动作戏", "斗法", "对战", "决战", "武打"],
               "c": {"动作": ["戏", "场面", "打斗", "战斗", "流畅", "酷", "爽", "帅气"]}},
        "es": {"w": ["pelea", "peleas", "combate"],
               "p": ["escena de pelea", "escenas de pelea"], "c": {}},
        "id": {"w": ["pertarungan"], "p": ["adegan pertarungan"], "c": {}},
    },
    "pacing_length": {
        "zh_label": "节奏与时长", "en_label": "Pacing & Length",
        "en": {
            "w": ["pacing", "rushed", "filler", "dragged", "binge", "slow-paced", "fast-paced"],
            "p": ["slow paced", "slow pace", "fast paced", "fast pace", "too slow",
                  "slow start", "rushed ending", "episode length", "pacing issue",
                  "pacing problem", "pacing is", "pacing feels", "slow burn", "slowburn", "pretty slow"],
            "c": {"slow": ["pacing", "pace", "start", "beginning", "episode", "story",
                           "build", "burn", "节奏", "剧情", "慢热"],
                  "short": ["episode", "episodes", "run", "season", "太短", "集"]},
        },
        "zh": {"w": ["节奏", "拖沓", "慢热", "时长", "篇幅", "集数", "紧凑", "太短", "拖戏"],
               "c": {"水": ["剧情", "集", "话", "拖", "节奏"]}},
        "es": {"w": ["ritmo"],
               "p": ["ritmo lento", "muy lenta", "demasiado lenta", "muy lento", "demasiado lento"],
               "c": {"lento": ["ritmo", "episodio", "capítulo", "historia", "inicio", "principio", "trama", "serie"],
                     "lenta": ["ritmo", "serie", "historia", "trama", "episodio", "temporada", "inicio", "principio"]}},
        "id": {"w": ["durasi"],
               "p": ["terlalu pendek", "terlalu lambat", "terlalu singkat"],
               "c": {"lambat": ["durasi", "cerita", "episode", "animasi", "pertarungan", "ritme", "jalannya"]}},
    },
    "music_voice": {
        "zh_label": "音乐与配音", "en_label": "Music & Voice",
        "en": {
            "w": ["ost", "soundtrack", "music", "bgm", "vocal", "instrumental", "voice acting",
                  "lyric", "lyrics", "song"],
            "p": ["voice acting", "voice actor", "theme song", "opening theme",
                  "ending theme", "background music", "sound track", "opening song", "ending song"],
            "c": {},
        },
        "zh": {"w": ["音乐", "配乐", "配音", "声优", "音效", "主题曲", "片头曲", "片尾曲", "插曲", "歌声", "歌曲"], "c": {}},
        "es": {"w": ["doblaje"],
               "c": {"voz": ["doblaje", "personaje", "personajes", "actriz", "actor", "escena", "canción", "tema"],
                     "voces": ["doblaje", "personaje", "personajes", "actriz", "actor", "escena", "canción", "tema"]}},
        "ja": {"w": ["主題歌", "音楽", "オープニング", "エンディング", "サントラ", "テーマ曲"], "p": [], "c": {}},
    },
    "chinese_culture": {
        "zh_label": "中国文化表达", "en_label": "Chinese Culture",
        "en": {
            "w": ["wuxia", "xianxia", "taoist", "taoism", "daoist", "daoism",
                  "chinese culture", "chinese mythology", "chinese folklore",
                  "chinese tradition", "chinese history", "ancient china", "chinese philosophy"],
            "p": ["chinese culture", "chinese mythology", "chinese folklore",
                  "chinese tradition", "chinese history", "ancient china",
                  "chinese philosophy", "traditional chinese", "chinese legend"],
            "c": {},
        },
        "zh": {"w": ["中华文化", "中国文化", "传统文化", "神话", "武侠", "仙侠", "道家",
                     "国风", "民间传说", "历史", "文化底蕴", "中华", "中式"],
               "c": {"文化": ["中华", "中国", "传统", "底蕴", "内涵", "武侠", "仙侠", "道家", "丰富", "浓厚", "东方"],
                     "传统": ["文化", "元素", "中国", "中华", "武侠", "戏曲", "风格", "节日"]}},
    },
    "subtitle_locale": {
        "zh_label": "字幕与本地化", "en_label": "Subtitle & Localization",
        "en": {
            "w": ["subtitle", "subtitles", "translation", "translated", "localization",
                  "localisation", "caption", "subbed", "dub", "subs"],
            "p": ["english subtitles", "english sub", "eng sub", "eng subs", "english dub",
                  "eng dub", "subtitle quality", "translation quality", "proper subtitles",
                  "fan sub", "official sub"],
            "c": {"translat": ["subtitle", "subtitles", "quality", "official", "localization", "字幕", "翻译", "错"],
                  "dub": ["english", "eng", "localization", "voice", "字幕", "配音", "翻译"]},
        },
        "zh": {"w": ["字幕", "翻译", "本地化", "汉化", "中文字幕", "英文字幕", "翻译质量", "错译", "字幕组"],
               "c": {"配音": ["英文", "国语", "中文", "日语", "原声", "版本", "质量"]}},
        "es": {"w": ["traducción", "traduccion", "subtítulos", "subtitulos"], "p": [], "c": {}},
        "id": {"w": ["terjemahan"], "p": [], "c": {}},
    },
    "release_availability": {
        "zh_label": "海外发行与观看渠道", "en_label": "Release & Availability",
        "en": {
            "w": ["streaming", "stream", "crunchyroll", "netflix", "simulcast", "availability",
                  "licensed", "broadcast", "aired", "airing", "hulu", "dvd", "blu-ray", "bluray",
                  "pirated", "digital"],
            "p": ["where to watch", "not available", "available on", "watch it on",
                  "watch order", "watch legally", "release date", "release schedule",
                  "official release", "legally available", "on netflix", "on crunchyroll", "for free",
                  "on digital", "hit digital", "available digitally"],
            "c": {"release": ["date", "announced", "season", "episode", "series", "anime",
                              "donghua", "official", "next", "发行", "上映", "播出", "首播", "上线", "更新", "中文"],
                  "platform": ["watch", "watching", "stream", "streaming", "available",
                               "crunchyroll", "netflix", "site", "website", "app", "youtube", "bilibili",
                               "观看", "看", "在哪", "哪里", "上线", "播出", "会员", "下载"]},
        },
        "zh": {"w": ["发行", "上映", "播出", "首播", "上线", "引进", "版权", "会员", "渠道", "资源", "发售", "上架", "购买"],
               "c": {"平台": ["看", "观看", "上线", "播出", "会员", "在哪", "哪里", "下载", "链接", "b站", "bilibili", "网飞", "crunchyroll"],
                     "观看": ["哪里", "在哪", "免费", "平台", "可以", "不能", "无法", "渠道", "正版"]}},
    },
    "awareness_marketing": {
        "zh_label": "传播与知名度", "en_label": "Awareness & Marketing",
        "en": {
            "w": ["underrated", "overrated", "viral", "trending", "mainstream", "popularity",
                  "exposure", "word of mouth", "widely known", "under-appreciated", "award",
                  "grossing", "buzz"],
            "p": ["well known", "more attention", "deserves more", "deserve more",
                  "word of mouth", "more popular", "not popular", "getting popular",
                  "become popular", "widely known", "popular in", "popular among",
                  "box office", "cultural impact", "highest grossing", "hype up", "hype"],
            "c": {"popular": ["in", "among", "globally", "worldwide", "overseas", "more",
                              "very", "really", "hugely", "become", "getting", "not", "underrated",
                              "国外", "海外", "国内", "很", "越来越", "不", "火", "知名"],
                  "famous": ["more", "very", "widely", "globally", "worldwide", "not", "知名", "出名", "火"]},
        },
        "zh": {"w": ["知名度", "宣传", "营销", "推广", "出圈", "热门", "安利", "口碑", "流行", "关注度",
                     "爆火", "冷门", "小众", "票房", "影响力"],
               "c": {"火": ["很", "更", "越来越", "爆", "不", "在国外", "国外", "海外", "国内", "很多人", "出圈"],
                     "出名": ["很", "不", "在国外", "海外", "国内", "知名"]}},
    },
    "ip_derivative": {
        "zh_label": "IP及衍生开发", "en_label": "IP & Derivatives",
        "en": {
            "w": ["merchandise", "merch", "figurine", "figures", "spin-off", "spinoff",
                  "adaptation", "adaption", "sequel", "prequel", "cosplay", "reboot",
                  "light novel", "manga", "manhua", "webtoon", "anime adaptation"],
            "p": ["video game", "video games", "mobile game", "anime adaptation",
                  "light novel", "spin off", "season 2", "season two", "second season",
                  "live action", "live-action", "tv adaptation", "official game", "redeem code"],
            "c": {"game": ["video", "mobile", "adaptation", "novel", "manga", "anime",
                           "donghua", "official", "手游", "改编", "官方", "玩法", "上线"],
                  "novel": ["light", "web", "original", "source", "reader", "改编", "小说", "原著", "原作"],
                  "comic": ["manga", "manhua", "webtoon", "adaptation", "改编", "漫画"],
                  "season": ["2", "two", "second", "3", "three", "third", "4", "4th", "next",
                             "续", "第二季", "第2季", "续作", "part"]},
        },
        "zh": {"w": ["衍生", "手办", "周边", "改编", "漫画", "小说", "续作", "第二季", "第2季",
                     "番外", "联动", "手游", "同名", "剧场版", "真人版", "动画化", "轻小说", "游戏"],
               "c": {}},
    },
}

# 每个主题的布尔列名（先固定顺序，保证 topic_list 输出顺序稳定）
TOPIC_IDS = list(TOPIC_LEXICON.keys())
TOPIC_COLS = ["topic_" + tid for tid in TOPIC_IDS]

_TRIGGERS = defaultdict(list)   # (topic_id, lang, term) -> [record_id, ...]，仅冒烟模式记录
LANG_PREFIX = {"en": "", "zh": "", "es": "es:", "id": "id:", "ja": "ja:"}


def _is_ascii(s: str) -> bool:
    return all(ord(c) < 128 for c in s)


def term_present(norm: str, t: str) -> bool:
    """判断词/短语是否出现：含非ASCII（中日韩/西语重音）或空格→子串；否则词边界+可选复数。"""
    if not norm:
        return False
    if not _is_ascii(t) or " " in t:
        return t in norm
    return re.search(r"\b" + re.escape(t) + r"(?:s|es)?\b", norm) is not None


def match_topic(norm: str, conf: dict, lang_group: str):
    """对单个主题配置返回命中列表 [(语言, 词, 是否共现)]。ja 块仅对日语组生效。"""
    hits = []
    for lang, _prefix, ja_only in LANG_BLOCKS:
        if ja_only and lang_group != JA_LANG:
            continue
        block = conf.get(lang)
        if not block:
            continue
        for t in block.get("w", []):
            if term_present(norm, t):
                hits.append((lang, t, False))
        for t in block.get("p", []):
            if term_present(norm, t):
                hits.append((lang, t, False))
        for t, cos in block.get("c", {}).items():
            if term_present(norm, t) and any(term_present(norm, c) for c in cos):
                hits.append((lang, t, True))
    return hits


def normalize_text(text: str) -> str:
    """规范化：小写、去 URL/@提及/#话题、合并空白。用于主题匹配。"""
    if not isinstance(text, str):
        return ""
    t = text.lower()
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"www\.\S+", " ", t)
    t = re.sub(r"@\w+", " ", t)
    t = re.sub(r"#[\w一-鿿]+", " ", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def label_one(norm: str, rid: str, lang_group: str, track: bool = False):
    """多标签标注单条文本。返回 (匹配主题id列表, 每主题命中词列表，外语词带语言前缀)。"""
    matched, kws = [], []
    for tid in TOPIC_IDS:
        hits = match_topic(norm, TOPIC_LEXICON[tid], lang_group)
        if hits:
            matched.append(tid)
            disp = []
            for lang, term, is_co in hits:
                d = LANG_PREFIX[lang] + term + ("*" if is_co else "")
                if d not in disp:
                    disp.append(d)
                if track:
                    _TRIGGERS[(tid, lang, term)].append(rid)
            kws.append(";".join(sorted(disp)))
    return matched, kws


def add_topic_columns(df: pd.DataFrame, track: bool = False) -> pd.DataFrame:
    """对全量 df 逐条标注，追加主题列；返回新 DataFrame（不改原对象）。"""
    out = df.copy()
    for c in TOPIC_COLS:
        out[c] = False
    out["topic_list"] = ""
    out["topic_count"] = 0
    out["topic_matched_keywords"] = ""
    for idx, row in out.iterrows():
        norm = normalize_text(row["content_clean"]) or normalize_text(row["content_raw"])
        matched, kws = label_one(norm, str(row["record_id"]), str(row["lang_group"]), track=track)
        for tid, kw in zip(matched, kws):
            out.at[idx, "topic_" + tid] = True
        if matched:
            out.at[idx, "topic_list"] = "；".join(TOPIC_LEXICON[t]["zh_label"] for t in matched)
            out.at[idx, "topic_matched_keywords"] = " || ".join(kws)
        out.at[idx, "topic_count"] = len(matched)
    out["topic_unmatched"] = out["topic_count"] == 0
    return out


# ---------------------------------------------------------------------------
# 2. 统计口径
# ---------------------------------------------------------------------------
def topic_counts(df: pd.DataFrame) -> pd.Series:
    """每个主题被提及的评论条数（多标签，各主题计数互斥相加≠总评论数）。"""
    return pd.Series(
        {TOPIC_LEXICON[t]["zh_label"]: int(df["topic_" + t].sum()) for t in TOPIC_IDS},
        name="提及评论数",
    )


# ---------------------------------------------------------------------------
# 3. 图表
# ---------------------------------------------------------------------------
def plot_topic_bar(counts: pd.Series, title: str, fname: str):
    counts = counts.sort_values()
    fig, ax = plt.subplots(figsize=(8, max(4, len(counts) * 0.45)))
    ax.barh(counts.index, counts.values, color=matplotlib.colormaps["viridis"](
        np.linspace(0.25, 0.9, len(counts))))
    for i, v in enumerate(counts.values):
        ax.text(v + 0.5, i, str(int(v)), va="center", fontsize=9)
    ax.set_xlabel("提及评论条数（多标签口径，占比不可相加为100%）")
    ax.set_title(title)
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    plt.savefig(fname, dpi=150)
    plt.close(fig)


def plot_heatmap(data: pd.DataFrame, title: str, fname: str, xlabel: str, ylabel: str):
    vals = data.to_numpy(dtype=float, na_value=np.nan)  # 空DF列默认object，imshow需数值
    fig, ax = plt.subplots(figsize=(max(7, data.shape[1] * 1.15), max(4.5, data.shape[0] * 0.55)))
    cm = matplotlib.colormaps["YlGnBu"]
    vmax = max(1, int(np.nanmax(vals))) if vals.size else 1
    im = ax.imshow(vals, cmap=cm, norm=mcolors.Normalize(vmin=0, vmax=vmax), aspect="auto")
    ax.set_xticks(range(data.shape[1]))
    ax.set_xticklabels(data.columns, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(data.shape[0]))
    ax.set_yticklabels(data.index, fontsize=8)
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            v = vals[i, j]
            if pd.notna(v) and v > 0:
                ax.text(j, i, str(int(v)), ha="center", va="center", fontsize=7)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    fig.colorbar(im, ax=ax, fraction=0.03)
    plt.tight_layout()
    plt.savefig(fname, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------------
# 4. 冒烟抽样（配额 + 定向补足）
# ---------------------------------------------------------------------------
SMOKE_QUOTA = {"YouTube": 35, "X": 30, "Reddit": 25, "AniList": 10}


def build_smoke_sample(df: pd.DataFrame, size: int = 100) -> pd.DataFrame:
    rng = random.Random(42)
    chosen = set()
    src_ids = {s: set(df[df["source"] == s]["record_id"]) for s in SMOKE_QUOTA}
    anime_ids = {a: set(df[df["anime_name"] == a]["record_id"]) for a in df["anime_name"].unique()}
    other_lang = set(df[~df["lang_group"].isin(CORE_LANGS)]["record_id"])
    core = set()

    def pick(pool_ids, n):
        pool = [i for i in pool_ids if i not in chosen]
        rng.shuffle(pool)
        return pool[:n]

    # 1) 负面/混合：多带几条（按 平台×作品 分散抽取，避免集中在一部作品）
    for sent, n in [("negative", 15), ("mixed", 15)]:
        sub = df[df["sentiment_final"] == sent]
        grp = sub.groupby(["source", "anime_name"])["record_id"].apply(list).reset_index()
        order = grp.index.tolist()
        rng.shuffle(order)
        got = []
        for gi in order:
            for rid in grp.iloc[gi]["record_id"]:
                if rid not in chosen and rid not in got:
                    got.append(rid)
                if len(got) >= n:
                    break
            if len(got) >= n:
                break
        got = got[:n]
        chosen.update(got)
        core.update(got)

    # 2) 保证 7 部作品全覆盖（每部 1 条锚点）
    for anime, ids in anime_ids.items():
        pool = [i for i in sorted(ids) if i not in chosen]
        if pool:
            rng.shuffle(pool)
            chosen.add(pool[0])
            core.add(pool[0])

    # 3) 长文本：按 content_length 取前若干条
    long_ids = df.sort_values("content_length", ascending=False)["record_id"].tolist()
    got = pick(long_ids, 8)
    chosen.update(got)
    core.update(got)

    # 4) 非中英语言：至少 15 条（供判断是否扩词库）
    pool = sorted(other_lang - chosen)
    rng.shuffle(pool)
    need_other = 15 - len(chosen & other_lang)
    if need_other > 0:
        got = pool[:need_other]
        chosen.update(got)
        core.update(got)

    # 5) 平台配额填充到整 100
    for s, q in SMOKE_QUOTA.items():
        cur = len(chosen & src_ids[s])
        need = q - cur
        if need > 0:
            pool = sorted(src_ids[s] - chosen)
            rng.shuffle(pool)
            chosen.update(pool[:need])

    # 6) 收尾：略超/不足时微调至恰好 size
    extras = [i for i in chosen if i not in core]
    while len(chosen) > size and extras:
        chosen.remove(extras.pop())
    if len(chosen) < size:
        rest = [i for i in df["record_id"] if i not in chosen]
        rng.shuffle(rest)
        chosen.update(rest[: size - len(chosen)])

    return df[df["record_id"].isin(chosen)].copy()


# ---------------------------------------------------------------------------
# 5. 代表评论候选（平台内代表性筛选）
# ---------------------------------------------------------------------------
def rating_rep_score(g: pd.DataFrame) -> pd.Series:
    """评分型平台代表分：score 是评分非互动量，用信息量/主题覆盖/评分极端性/完整度综合。"""
    g = g.copy()
    length_r = g["content_length"].rank(pct=True)
    topic_r = g["topic_count"].rank(pct=True)
    score_num = g["score"].astype(float)
    extreme_r = (score_num - score_num.median()).abs().rank(pct=True)
    n_sent = g["content_raw"].fillna("").astype(str).apply(
        lambda s: len(re.findall(r"[.!?。！？…！？]", s)))
    complete_r = ((n_sent >= 2) | (g["content_length"] >= 150)).astype(int).rank(pct=True)
    return 0.35 * length_r + 0.20 * topic_r + 0.25 * extreme_r + 0.20 * complete_r


def rep_rank_within_platform(g: pd.DataFrame) -> pd.Series:
    """平台内代表性分：互动型平台用 score 平台内百分位；评分型平台用综合分。"""
    r = pd.Series(np.nan, index=g.index)
    for p in g["source"].unique():
        idx = g.index[g["source"] == p]
        if p in RATING_PLATFORMS:
            r.loc[idx] = rating_rep_score(g.loc[idx]).values
        else:
            r.loc[idx] = g.loc[idx, "score"].rank(pct=True).values
    return r


def top_rep_by_platform(g: pd.DataFrame, n: int):
    """组内按平台多样取代表性前 n 条（每平台先取最优，再补次优）。"""
    g = g.sort_values("_rep", ascending=False)
    out = []
    for p in g["source"].unique():
        best = g[g["source"] == p].iloc[0]
        if best.name not in out:
            out.append(best.name)
        if len(out) >= n:
            break
    if len(out) < n:
        for idx in g.index:
            if idx not in out:
                out.append(idx)
            if len(out) >= n:
                break
    return out


def select_sentiment_reps(df: pd.DataFrame):
    """情感代表：每 作品×情感 实际存在的组合内取 1~2 条（正面2、中性1、混合2、负面2）。"""
    cap = {"positive": 2, "neutral": 1, "mixed": 2, "negative": 2}
    chosen = []
    for (anime, sent), grp in df.groupby(["anime_name", "sentiment_final"]):
        if sent not in cap:
            continue
        g = grp.copy()
        g["_rep"] = rep_rank_within_platform(g)
        for idx in top_rep_by_platform(g, cap[sent]):
            chosen.append((idx, f"情感代表·{SENT_ZH[sent]}·平台内代表性最高"))
    return chosen


def select_high_interaction(df: pd.DataFrame):
    """高互动代表：互动型平台按 score 取前5（控作品集中度）；评分型平台用综合分前5。"""
    chosen = []
    rows = df.copy()
    for p in INTERACTION_PLATFORMS:
        sub = rows[rows["source"] == p].sort_values("score", ascending=False)
        top = []
        for idx, row in sub.iterrows():
            if len(top) >= 5:
                break
            anime = row["anime_name"]
            if sum(1 for i in top if df.at[i, "anime_name"] == anime) < 2:
                top.append(idx)
        for idx in top:
            chosen.append((idx, f"平台内高互动·{p}·score前5"))
    for p in RATING_PLATFORMS:
        sub = rows[rows["source"] == p]
        if len(sub):
            sub = sub.copy()
            sub["_rep"] = rating_rep_score(sub)
            for idx in sub.sort_values("_rep", ascending=False).head(5).index:
                chosen.append((idx, f"{p}代表性·信息量/主题覆盖/评分极端/完整度"))
    return chosen


def select_topic_reps(df: pd.DataFrame):
    """主题代表：每个主题下每作品取平台内代表性最高 1 条。"""
    chosen = []
    for tid in TOPIC_IDS:
        col = "topic_" + tid
        sub = df[df[col]]
        if not len(sub):
            continue
        sub = sub.copy()
        sub["_rep"] = rep_rank_within_platform(sub)
        for anime in sub["anime_name"].unique():
            g = sub[sub["anime_name"] == anime].sort_values("_rep", ascending=False)
            idx = g.index[0]
            chosen.append((idx, f"主题代表·{TOPIC_LEXICON[tid]['zh_label']}·平台内代表性最高"))
    return chosen


def _topic_set(df: pd.DataFrame, idx) -> set:
    return {t for t in TOPIC_IDS if df.at[idx, "topic_" + t]}


def filter_near_dup(pool: pd.DataFrame, threshold: float = 0.90):
    """近重复：只在 同一作品×共享主题 内比较，相似度≥阈值只保留代表性更高者。"""
    pool = pool.sort_values("_rep", ascending=False).copy()
    pool["_norm"] = pool["content_raw"].fillna("").astype(str).apply(
        lambda s: normalize_text(s))
    kept = []
    kept_topic = {}
    for idx, row in pool.iterrows():
        dup = False
        rt = _topic_set(pool, idx)
        for k in kept:
            if row["anime_name"] != pool.at[k, "anime_name"]:
                continue
            if not (rt & kept_topic[k]):
                continue
            a, b = row["_norm"], pool.at[k, "_norm"]
            if a and b and SequenceMatcher(None, a, b).ratio() >= threshold:
                dup = True
                break
        if not dup:
            kept.append(idx)
            kept_topic[idx] = rt
    return pool.loc[kept]


def build_representative_pool(df: pd.DataFrame) -> pd.DataFrame:
    """合并三类来源，去重、近重复过滤、按 每作品≤10 / 总量≤70 裁剪。"""
    base = df[df["sentiment_final"] != "other"].copy()
    # 已知重复排除（duplicate_flag 目前全为0，留作防护；兼容 int/float/字符串三种形态）
    dup_mask = base["duplicate_flag"].fillna(0).map(
        lambda v: str(v).strip().lower() not in ("", "0", "0.0", "nan", "none"))
    base = base.drop(index=base.index[dup_mask], errors="ignore")

    reasons = {}
    for src, added in [
        ("情感", select_sentiment_reps(base)),
        ("高互动", select_high_interaction(base)),
        ("主题", select_topic_reps(base)),
    ]:
        for idx, reason in added:
            reasons.setdefault(idx, set()).add(reason)

    pool = base.loc[list(reasons)].copy()
    pool["_rep"] = rep_rank_within_platform(pool)
    pool["入选理由"] = pool.index.map(lambda i: "；".join(sorted(reasons[i])))

    # 优先级：情感=1 < 高互动=2 < 主题=3
    prio = {"情感": 1, "高互动": 2, "主题": 3}
    pool["_prio"] = pool["入选理由"].apply(
        lambda s: min(prio[k] for k in prio if k in s))

    # 近重复过滤（同作品×同主题内，相似度≥0.90 只留代表性更高者）
    pool = filter_near_dup(pool, threshold=0.90)

    # 每作品 ≤10，总量 ≤70（按 情感>高互动>主题 优先级取舍）
    pool = pool.sort_values(["_prio", "_rep"], ascending=[True, False])
    keep_anime = {}
    ordered = []
    for idx in pool.index:
        anime = pool.at[idx, "anime_name"]
        if keep_anime.get(anime, 0) >= 10:
            continue
        if len(ordered) >= 70:
            break
        ordered.append(idx)
        keep_anime[anime] = keep_anime.get(anime, 0) + 1
    return pool.loc[ordered]


def export_representative(pool: pd.DataFrame, fname: str):
    cols = ["record_id", "anime_name", "source", "sentiment_final", "topic_list",
            "score", "lang_group", "content_length", "page_url", "content_raw", "入选理由"]
    out = pd.DataFrame(index=pool.index, columns=cols)
    for idx, row in pool.iterrows():
        out.at[idx, "record_id"] = row["record_id"]
        out.at[idx, "anime_name"] = row["anime_name"]
        out.at[idx, "source"] = row["source"]
        out.at[idx, "sentiment_final"] = SENT_ZH.get(row["sentiment_final"], row["sentiment_final"])
        out.at[idx, "topic_list"] = row["topic_list"]
        out.at[idx, "score"] = row["score"]
        out.at[idx, "lang_group"] = row["lang_group"]
        out.at[idx, "content_length"] = row["content_length"]
        out.at[idx, "page_url"] = row["page_url"]
        out.at[idx, "content_raw"] = row["content_raw"]
        out.at[idx, "入选理由"] = row["入选理由"]
    out["中文意译"] = ""   # 留空，人工最终选中 30~40 条后再翻译
    out = out[["record_id", "anime_name", "source", "sentiment_final", "topic_list",
               "score", "lang_group", "content_length", "page_url", "content_raw",
               "中文意译", "入选理由"]]
    out["sentiment_final"] = out["sentiment_final"].map(lambda x: SENT_ZH.get(x, x))
    out.to_excel(fname, index=False)
    return out


# ---------------------------------------------------------------------------
# 6. 冒烟报告
# ---------------------------------------------------------------------------
def build_smoke_report(sample: pd.DataFrame, fname: str):
    total = len(sample)
    hit = sample[~sample["topic_unmatched"]]
    n_hit = len(hit)
    miss = sample[sample["topic_unmatched"]]

    # 命中概况
    overview = pd.DataFrame({
        "项目": ["样本总数", "命中≥1主题", "未命中(词库未识别)", "命中率", "平均主题数/命中条"],
        "数值": [total, n_hit, total - n_hit,
                 f"{n_hit / total:.1%}", f"{hit['topic_count'].mean():.2f}"],
    })

    # 每主题命中条数
    per_topic = topic_counts(sample).sort_values(ascending=False).rename("命中条数").reset_index()
    per_topic.columns = ["主题", "命中条数"]

    # 每主题命中示例
    examples = []
    for tid in TOPIC_IDS:
        sub = sample[sample["topic_" + tid]]
        for _, row in sub.head(3).iterrows():
            examples.append({
                "主题": TOPIC_LEXICON[tid]["zh_label"],
                "record_id": row["record_id"],
                "平台": row["source"],
                "命中词": row["topic_matched_keywords"],
                "原文短摘": str(row["content_raw"])[:120],
            })
    ex_df = pd.DataFrame(examples, columns=["主题", "record_id", "平台", "命中词", "原文短摘"])

    # 关键词触发统计（每个关键词命中条数 + 2 个样例；外语词带语言前缀）
    sample_ids = set(sample["record_id"])
    kw_rows = []
    lang_hit = defaultdict(lambda: {"hits": 0, "comments": set()})
    for (tid, lang, term), rids in sorted(_TRIGGERS.items(), key=lambda kv: -len(kv[1])):
        sample_rids = [r for r in rids if r in sample_ids]
        if not sample_rids:
            continue
        ex = []
        for r in sample_rids[:2]:
            row = sample[sample["record_id"] == r].iloc[0]
            ex.append(str(row["content_raw"])[:80])
        for r in sample_rids:
            lang_hit[lang]["hits"] += 1
            lang_hit[lang]["comments"].add(r)
        kw_rows.append({
            "主题": TOPIC_LEXICON[tid]["zh_label"],
            "词库语言": lang,
            "关键词": LANG_PREFIX[lang] + term,
            "命中条数": len(sample_rids),
            "样例1": ex[0] if len(ex) > 0 else "",
            "样例2": ex[1] if len(ex) > 1 else "",
        })
    kw_df = pd.DataFrame(kw_rows, columns=["主题", "词库语言", "关键词", "命中条数", "样例1", "样例2"])

    # 按词库语言统计命中（需求点9：区分 en/zh/es/id）
    lang_hit_df = pd.DataFrame(
        [{"词库语言": lang, "关键词命中次数": v["hits"], "涉及去重评论数": len(v["comments"])}
         for lang, v in sorted(lang_hit.items())],
        columns=["词库语言", "关键词命中次数", "涉及去重评论数"])

    # 语言命中率（全量语言组，抽样范围内）
    lang_rows = []
    for lg, g in sample.groupby("lang_group"):
        h = (~g["topic_unmatched"]).sum()
        lang_rows.append({"语言组": lg, "样本数": len(g), "命中": int(h),
                          "未命中": int(len(g) - h),
                          "命中率": f"{h / len(g):.1%}"})
    lang_df = pd.DataFrame(lang_rows, columns=["语言组", "样本数", "命中", "未命中", "命中率"])

    # 未命中清单（词库未识别；非中英优先列出原文供目测是否扩词）
    miss_rows = []
    miss = miss.sort_values(["lang_group", "score"], ascending=[True, False])
    for _, row in miss.iterrows():
        miss_rows.append({
            "record_id": row["record_id"], "语言组": row["lang_group"],
            "平台": row["source"], "作品": row["anime_name"],
            "情感": SENT_ZH.get(row["sentiment_final"], row["sentiment_final"]),
            "score": row["score"], "是否非中英": row["lang_group"] not in CORE_LANGS,
            "原文": str(row["content_raw"])[:200],
        })
    miss_df = pd.DataFrame(miss_rows, columns=["record_id", "语言组", "平台", "作品", "情感", "score", "是否非中英", "原文"])
    other_lang_miss = miss_df[miss_df["是否非中英"]]

    # 抽样构成（长表：维度/取值/条数，避免各维度索引错配）
    comp_rows = []
    for dim, series in [("平台", sample["source"]), ("作品", sample["anime_name"]),
                        ("情感", sample["sentiment_final"]), ("语言", sample["lang_group"])]:
        for k, v in series.value_counts().sort_index().items():
            comp_rows.append({"维度": dim, "取值": k, "条数": int(v)})
    comp = pd.DataFrame(comp_rows, columns=["维度", "取值", "条数"])

    with pd.ExcelWriter(fname, engine="openpyxl") as w:
        overview.to_excel(w, sheet_name="命中概况", index=False)
        comp.to_excel(w, sheet_name="抽样构成", index=False)
        per_topic.to_excel(w, sheet_name="每主题命中", index=False)
        ex_df.to_excel(w, sheet_name="每主题命中示例", index=False)
        kw_df.to_excel(w, sheet_name="关键词触发统计", index=False)
        lang_hit_df.to_excel(w, sheet_name="词库语言命中", index=False)
        lang_df.to_excel(w, sheet_name="语言命中率", index=False)
        miss_df.to_excel(w, sheet_name="未命中清单", index=False)
        other_lang_miss.to_excel(w, sheet_name="非中英未命中原文", index=False)

    # 控制台摘要
    print("=" * 60)
    print(f"[冒烟] 样本 {total} 条：命中 {n_hit} ({n_hit / total:.1%})，"
          f"未命中(词库未识别) {total - n_hit}，平均主题数 {hit['topic_count'].mean():.2f}")
    print("每主题命中：")
    for _, r in per_topic.iterrows():
        print(f"   {r['主题']}: {r['命中条数']}")
    print("语言命中率：")
    for _, r in lang_df.sort_values("样本数", ascending=False).iterrows():
        print(f"   {r['语言组']}: 样本{r['样本数']} 命中{r['命中']} 未命中{r['未命中']} ({r['命中率']})")
    print(f"未命中清单 {len(miss_df)} 条，其中非中英 {len(other_lang_miss)} 条（原文见报告）")
    print(f"输出 -> {fname}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# 7. 全量统计 + 产出
# ---------------------------------------------------------------------------
def build_full_outputs(df: pd.DataFrame):
    # 统计基数：排除 other
    base = df[df["sentiment_final"] != "other"]
    other = df[df["sentiment_final"] == "other"]
    n_base = len(base)
    zh = {t: TOPIC_LEXICON[t]["zh_label"] for t in TOPIC_IDS}

    # --- 05_topic_labeled.csv（全量，含 other，保留审计字段） ---
    df.to_csv(PREFIX + "topic_labeled.csv", index=False, encoding="utf-8-sig")
    print(f"输出 {PREFIX}topic_labeled.csv：{len(df)} 条 × {df.shape[1]} 列")

    # --- 总体主题分布 ---
    overall = topic_counts(base).sort_values(ascending=False).reset_index()
    overall["占基数评论比"] = (overall["提及评论数"] / n_base).map(lambda v: f"{v:.1%}")
    overall.columns = ["主题", "提及评论数", "占基数评论比(多标签，不可相加为100%)"]

    # --- 主题×情感 ---
    pivot_sent = pd.DataFrame(index=[zh[t] for t in TOPIC_IDS], columns=SENT_ORDER)
    for t in TOPIC_IDS:
        for s in SENT_ORDER:
            pivot_sent.at[zh[t], s] = int(base[base["topic_" + t] & (base["sentiment_final"] == s)].shape[0])
    pivot_sent["合计"] = pivot_sent.sum(axis=1)

    # --- 作品×主题 ---
    pivot_anime = pd.DataFrame(index=[zh[t] for t in TOPIC_IDS],
                               columns=sorted(base["anime_name"].unique()))
    for t in TOPIC_IDS:
        for a in pivot_anime.columns:
            pivot_anime.at[zh[t], a] = int(base[(base["topic_" + t]) & (base["anime_name"] == a)].shape[0])
    pivot_anime["合计"] = pivot_anime.sum(axis=1)

    # --- 平台×主题 ---
    pivot_src = pd.DataFrame(index=[zh[t] for t in TOPIC_IDS],
                             columns=sorted(base["source"].unique()))
    for t in TOPIC_IDS:
        for s in pivot_src.columns:
            pivot_src.at[zh[t], s] = int(base[(base["topic_" + t]) & (base["source"] == s)].shape[0])
    pivot_src["合计"] = pivot_src.sum(axis=1)

    # --- 多标签分布（每条命中主题数） ---
    dist = base["topic_count"].value_counts().sort_index().reset_index()
    dist.columns = ["命中主题数", "评论条数"]
    dist["占基数评论比"] = (dist["评论条数"] / n_base).map(lambda v: f"{v:.1%}")

    # --- 语言命中率（全量） ---
    lang_rows = []
    for lg, g in df.groupby("lang_group"):
        h = int((~g["topic_unmatched"]).sum())
        lang_rows.append({"语言组": lg, "评论数": len(g), "命中": h,
                          "未命中": int(len(g) - h), "命中率": f"{h / len(g):.1%}"})
    lang_df = pd.DataFrame(lang_rows)

    # --- 其他语言未命中审计（高互动/负面/混合重点标记） ---
    other_lang = df[(~df["lang_group"].isin(CORE_LANGS)) & df["topic_unmatched"]]
    other_lang = other_lang.copy()
    # 平台内高互动标记（各平台 score 前 20%）
    high_inter = set()
    for p in other_lang["source"].unique():
        sub = other_lang[other_lang["source"] == p]
        thr = sub["score"].quantile(0.8)
        high_inter.update(sub[sub["score"] >= thr].index)
    other_lang["高互动(平台内前20%)"] = other_lang.index.isin(high_inter)
    other_lang["负面/混合"] = other_lang["sentiment_final"].isin(["negative", "mixed"])
    audit = other_lang[[
        "record_id", "lang_group", "source", "anime_name", "sentiment_final", "score",
        "content_length", "content_raw", "page_url", "高互动(平台内前20%)", "负面/混合",
    ]].copy()
    audit["sentiment_final"] = audit["sentiment_final"].map(lambda x: SENT_ZH.get(x, x))

    # --- 未命中复核样本（按语言分层，每语言组≤5，优先负面/混合/高互动） ---
    review_rows = []
    for lg, g in df[df["topic_unmatched"]].groupby("lang_group"):
        g = g.sort_values(["score", "content_length"], ascending=False)
        got = []
        for idx, row in g.iterrows():
            if len(got) >= 5:
                break
            if len(got) == 0 or row["sentiment_final"] in ("negative", "mixed"):
                got.append(idx)
        if len(got) < 5:
            for idx, row in g.iterrows():
                if len(got) >= 5:
                    break
                if idx not in got:
                    got.append(idx)
        for idx in got:
            row = g.loc[idx]
            review_rows.append({
                "record_id": row["record_id"], "语言组": lg, "平台": row["source"],
                "作品": row["anime_name"],
                "情感": SENT_ZH.get(row["sentiment_final"], row["sentiment_final"]),
                "score": row["score"], "原文": str(row["content_raw"])[:200],
                "人工主题/备注": "",
            })
    review_df = pd.DataFrame(review_rows)

    # --- 未命中全量清单 ---
    all_miss = df[df["topic_unmatched"]][[
        "record_id", "lang_group", "source", "anime_name", "sentiment_final",
        "score", "content_length", "content_raw", "page_url",
    ]].copy()
    all_miss["sentiment_final"] = all_miss["sentiment_final"].map(lambda x: SENT_ZH.get(x, x))

    # --- other 样本审计 ---
    other_s = other[[
        "record_id", "lang_group", "source", "anime_name", "sentiment_final",
        "topic_list", "content_raw", "page_url",
    ]].copy()

    # --- 说明 ---
    notes = pd.DataFrame({
        "项目": [
            "输入", "统计基数", "多标签口径",
            "topic_unmatched含义", "其他语言定义",
            "score比较", "生成时间",
        ],
        "说明": [
            f"{INPUT}（{len(df)} 条）",
            f"sentiment_final≠other 共 {n_base} 条；other {len(other)} 条仅审计不参与统计",
            "一条评论可命中多个主题，各主题计数/占比是提及该主题的评论数，各主题占比不可相加为100%",
            "topic_unmatched=True 仅表示未被当前中英词库识别，不等于无主题/无有效观点",
            f"其他语言 = lang_group 不属于 {sorted(CORE_LANGS)}",
            "score 仅在平台内部比较（Reddit karma/YouTube·X点赞/AniList评分），AniList用信息量等综合分",
            pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        ],
    })

    with pd.ExcelWriter(PREFIX + "topic_summary.xlsx", engine="openpyxl") as w:
        notes.to_excel(w, sheet_name="说明", index=False)
        overall.to_excel(w, sheet_name="总体主题分布", index=False)
        pivot_sent.to_excel(w, sheet_name="主题x情感")
        pivot_anime.to_excel(w, sheet_name="作品x主题")
        pivot_src.to_excel(w, sheet_name="平台x主题")
        dist.to_excel(w, sheet_name="多标签分布", index=False)
        lang_df.to_excel(w, sheet_name="语言命中率", index=False)
        audit.to_excel(w, sheet_name="其他语言未命中审计", index=False)
        review_df.to_excel(w, sheet_name="未命中复核样本", index=False)
        all_miss.to_excel(w, sheet_name="未命中全量清单", index=False)
        other_s.to_excel(w, sheet_name="other样本审计", index=False)
    print(f"输出 {PREFIX}topic_summary.xlsx（11 张表）")

    # --- 图表 ---
    plot_topic_bar(topic_counts(base), "总体主题分布（多标签口径）", PREFIX + "topic_overall_distribution.png")
    plot_heatmap(pivot_sent.drop(columns="合计"), "主题×情感 评论数", PREFIX + "topic_sentiment_distribution.png",
                 "情感", "主题")
    plot_heatmap(pivot_anime.drop(columns="合计"), "作品×主题 评论数", PREFIX + "topic_anime_heatmap.png",
                 "作品", "主题")
    plot_heatmap(pivot_src.drop(columns="合计"), "平台×主题 评论数", PREFIX + "topic_platform_heatmap.png",
                 "平台", "主题")
    print("输出 4 张 PNG 图表")

    # --- 代表评论候选 ---
    pool = build_representative_pool(df)
    rep = export_representative(pool, PREFIX + "representative_comments.xlsx")
    print(f"代表评论候选：{len(rep)} 条（每作品分布：")
    for a, c in rep["anime_name"].value_counts().sort_index().items():
        print(f"   {a}: {c}")
    print(")")


# ---------------------------------------------------------------------------
# 8. main
# ---------------------------------------------------------------------------
def main():
    global PREFIX, INPUT
    parser = argparse.ArgumentParser(description="主题多标签标注 + 统计 + 图表 + 代表评论候选")
    parser.add_argument("--input", default="04_sentiment_final.csv")
    parser.add_argument("--prefix", default="", help="输出文件名前缀，如 series_ / film_")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    INPUT = args.input
    PREFIX = args.prefix

    df = pd.read_csv(INPUT, encoding="utf-8-sig")
    # 关键数值列统一转数值（04 输出可能因空值被 pandas 读成字符串）
    for c in ["score", "content_length"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    print(f"读取 {INPUT}：{len(df)} 条 × {df.shape[1]} 列")

    if args.smoke:
        sample = build_smoke_sample(df, size=100)
        sample = add_topic_columns(sample, track=True)
        build_smoke_report(sample, PREFIX + "05_smoke_report.xlsx")
    else:
        df = add_topic_columns(df, track=False)
        build_full_outputs(df)


if __name__ == "__main__":
    main()
