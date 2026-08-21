# -*- coding: utf-8 -*-
"""
01_merge_clean_film.py —— Film 层（动画电影）数据合并 + 质量审计 + 相关性清洗

与 Series 版 01_merge_clean.py 的区别（关键）：
  1. score 保留浮点（不 int 化）—— RT 观众评分是 0.5~5 半星，int 化会丢半星，
     导致后面 03a 的「原生 score 一致性检查」失效。
  2. 输入来源分两类：
     a) storage2 的三份电影爬虫原始 CSV（RT / X / YouTube，9 列已规范）
     b) 原五平台数据里的 Ne Zha(2019) 252 条 + Ne Zha 2(AniList) 1 条，抽取进入 Film 层
  3. 输出到 storage2/film_pipeline/ 目录（与 Series 管线隔离，避免覆盖）。

输入明细（共 1176 条）：
    rt_film_data.csv         279 条  source=RT
    x_film_data.csv          233 条  source=X
    youtube_film_data.csv    411 条  source=YouTube
    Ne Zha(2019) 五平台       252 条  Reddit 75 + YouTube 89 + X 79 + MAL 9
    Ne Zha 2(AniList)          1 条  source=AniList

输出：
    01_merged_raw.csv       合并后原始数据集（统一列 + content_raw/clean + 基础审计字段）
    02_cleaned_all.csv      全部记录 + is_relevant/noise_reason/duplicate_flag
    02_cleaned_valid.csv    有效样本子集（is_relevant = True）
    cleaning_audit.xlsx     审计报表（总览 / 分平台 / 分作品 / 噪音明细 / 待复核样例）
"""
import re
import csv
import hashlib
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd

# ==================== 1. 路径配置 ====================
BASE = Path(__file__).resolve().parent          # storage2/film_pipeline
STORAGE2 = BASE.parent                           # storage2
PROJECT = STORAGE2.parent                        # 新建文件夹（项目根）

# 电影爬虫原始 CSV（9 列已规范，source 列已正确）
FILM_FILES = [
    (STORAGE2 / "rt_film_data.csv", "RT"),
    (STORAGE2 / "x_film_data.csv", "X"),
    (STORAGE2 / "youtube_film_data.csv", "YouTube"),
]

# 原五平台数据里要抽取进 Film 层的 Ne Zha / Ne Zha 2 记录
# (文件, 该文件对应的 source, 该文件里的 anime_name 取值)
NEZHA_EXTRACT = [
    (PROJECT / "reddit_comments.csv", "Reddit", {"Ne zha"}),
    (PROJECT / "anilist_data.csv", "AniList", {"Ne Zha 2"}),
    (PROJECT / "youtube_data.csv", "YouTube", {"Ne Zha"}),
    (PROJECT / "x_data.csv", "X", {"Ne Zha"}),
    (PROJECT / "mal_data.csv", "MAL", {"Ne Zha"}),
]

# 统一后的基础列（Reddit 的 subreddit 列会被归并到 source）
BASE_COLS = [
    "page_url", "anime_name", "source", "comment_id",
    "author", "post_time", "score", "crawl_time", "content",
]

# 输出文件
OUT_RAW = BASE / "01_merged_raw.csv"
OUT_ALL = BASE / "02_cleaned_all.csv"
OUT_VALID = BASE / "02_cleaned_valid.csv"
OUT_AUDIT = BASE / "cleaning_audit.xlsx"

# 太短阈值：中文字符满 2 个、或拉丁字母满 4 个即视为有实质内容
MIN_CJK = 2
MIN_LATIN = 4

# 广告/私聊链接信号（小写匹配 content_clean）
AD_OR_CHAT_PATTERNS = [
    "link in bio", "order link", "order in", "check bio",
    "payment", "bank transfer", "price and order",
    "dm me", "pm me", "private chat", "contact me",
    "text me", "my telegram", "my whatsapp",
    "add my telegram", "add my whatsapp", "add my snapchat", "add my wechat",
    "whatsapp", "telegram", "buy now", "discount code", "coupon",
    "私信", "加我", "微商", "代购", "刷赞", "刷粉", "刷播放", "下单", "加微信",
]

# 明显作品误匹配：出现这些字样通常意味着帖子跟动漫无关。
MISMATCH_MARKERS = [
    "法轮功",
    "falun gong", "falungong",
    "airtel", "jio", "vodafone",
    "ott subscription",
    "lottery", "casino", "betting", "gambling",
    "bitcoin", "ethereum", "crypto", "forex", "trading signals",
    "sweepstakes",
]
MISMATCH_PATTERNS = []
for _m in MISMATCH_MARKERS:
    if all(ord(_c) < 128 for _c in _m):
        MISMATCH_PATTERNS.append(re.compile(r"\b" + re.escape(_m) + r"\b"))
    else:
        MISMATCH_PATTERNS.append(re.compile(re.escape(_m)))

# anime_name 统一映射（Reddit 存的小写 'Ne zha' 归一化为 'Ne Zha'）
NAME_FIX = {
    "Ne zha": "Ne Zha",
    "Ne zha 2": "Ne Zha 2",
}

# 作品形式映射（Film 层全部为 film；兜底 unknown 便于排查误入的剧集）
FORM_MAP = {
    "Ne Zha": "film", "Ne Zha 2": "film", "White Snake": "film",
    "Jiang Ziya": "film", "New Gods: Nezha Reborn": "film",
    "New Gods: Yang Jian": "film", "I Am What I Am": "film",
}


# ==================== 2. 文本工具函数 ====================

URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
EMOJI_RE = re.compile(r"[\U0001F000-\U0001FAFF☀-➿️⌀-⏿⬀-⯿←-⇿]")
HTML_ENT_RE = re.compile(r"&(amp|lt|gt|quot|apos|nbsp|#\d+);")
CJK_RE = re.compile(r"[㐀-䶿一-鿿]")
KANA_RE = re.compile(r"[぀-ヿ]")
HANGUL_RE = re.compile(r"[가-힯]")
CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")
ARABIC_RE = re.compile(r"[؀-ۿ]")
DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")
THAI_RE = re.compile(r"[฀-๿]")
HEBREW_RE = re.compile(r"[֐-׿]")
LATIN_RE = re.compile(r"[A-Za-z]")


def clean_text(raw: str) -> str:
    """生成 content_clean：解 HTML 实体 -> 去掉链接 -> 压缩空白。"""
    if not raw:
        return ""
    s = HTML_ENT_RE.sub(" ", raw)
    s = URL_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalized(s: str) -> str:
    """标准化正文：去 @提及、小写、去表情、去标点、压缩空白。用于重复检测与 fallback 哈希。"""
    s = re.sub(r"@\w+", " ", s)
    s = EMOJI_RE.sub(" ", s)
    s = re.sub(r"[^\w\s㐀-鿿]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def detect_lang(text: str) -> str:
    """轻量脚本识别（无第三方依赖）。"""
    if not text:
        return "und"
    if CJK_RE.search(text):
        return "zh"
    if KANA_RE.search(text):
        return "ja"
    if HANGUL_RE.search(text):
        return "ko"
    if CYRILLIC_RE.search(text):
        return "ru"
    if ARABIC_RE.search(text):
        return "ar"
    if DEVANAGARI_RE.search(text):
        return "hi"
    if THAI_RE.search(text):
        return "th"
    if HEBREW_RE.search(text):
        return "he"
    if LATIN_RE.search(text):
        return "en"
    return "und"


def detect_noise(row: dict) -> list:
    """对单条记录返回噪音类型列表（可多个）。"""
    raw = row["content_raw"]
    content = row["content_clean"]
    flags = []

    cjk = len(CJK_RE.findall(content))
    latin = len(LATIN_RE.findall(content))
    has_url = bool(URL_RE.search(raw or ""))
    has_emoji = bool(EMOJI_RE.search(raw or ""))

    if not content:
        flags.append("empty_text")
    elif not cjk and not latin:
        if has_url:
            flags.append("pure_link")
        elif has_emoji:
            flags.append("pure_emoji")
        elif content.isdigit():
            flags.append("too_short")
        else:
            flags.append("empty_text")
    else:
        if cjk < MIN_CJK and latin < MIN_LATIN:
            flags.append("too_short")

    lower = content.lower()
    if any(p in lower for p in AD_OR_CHAT_PATTERNS):
        flags.append("ad_or_private_chat")

    for pat in MISMATCH_PATTERNS:
        if pat.search(lower):
            flags.append("work_mismatch")
            break

    return flags


def parse_score(v) -> float:
    """
    保留浮点评分（RT 半星 4.5 不被 int 化）。
    空 / 非法 → 0.0（与 Series 版「失败给 0」口径一致）。
    """
    v = (v or "").strip()
    if v == "":
        return 0.0
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0


# ==================== 3. 读取 + 合并 ====================

def read_file(path) -> list:
    """读取 CSV（utf-8-sig 优先，兼容 utf-8/gbk），返回 dict 行列表。"""
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            with open(path, encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except (UnicodeDecodeError, Exception):
            continue
    raise RuntimeError(f"无法读取 {path}（utf-8-sig / utf-8 / gbk 都失败）")


def load_film_files() -> list:
    """读三份电影爬虫 CSV，统一为 9 列，返回 [{col:value}, ...]。"""
    records = []
    for path, source in FILM_FILES:
        rows = read_file(path)
        for r in rows:
            rec = {}
            for col in BASE_COLS:
                if col == "source":
                    val = source
                else:
                    val = (r.get(col) or "").strip()
                rec[col] = val
            rec["score"] = parse_score(rec["score"])
            records.append(rec)
        print(f"  [电影CSV] {path.name}: {len(rows)} 条 (source={source})")
    return records


def load_nezha_from_5platform() -> list:
    """从原五平台数据抽取 Ne Zha / Ne Zha 2 记录，进入 Film 层。"""
    records = []
    for path, source, names in NEZHA_EXTRACT:
        rows = read_file(path)
        picked = [r for r in rows if r.get("anime_name", "").strip() in names]
        for r in picked:
            rec = {}
            for col in BASE_COLS:
                if col == "source":
                    val = source
                else:
                    val = (r.get(col) or "").strip()
                rec[col] = val
            rec["score"] = parse_score(rec["score"])
            records.append(rec)
        print(f"  [Ne Zha 抽取] {path.name}: {len(picked)} 条 (source={source}, names={names})")
    return records


# ==================== 4. 主流程 ====================

def main():
    print("========== Film 步骤1/4 读取并合并 ==========")
    records = load_film_files() + load_nezha_from_5platform()

    renamed = 0
    for r in records:
        fixed = NAME_FIX.get(r["anime_name"])
        if fixed:
            r["anime_name"] = fixed
            renamed += 1
        r["form"] = FORM_MAP.get(r["anime_name"], "unknown")

    print(f"\n合并总条数: {len(records)}")
    print(f"作品名归一化: {renamed} 条（Ne zha -> Ne Zha）")
    for src in ["RT", "X", "YouTube", "Reddit", "AniList", "MAL"]:
        n = sum(1 for r in records if r["source"] == src)
        print(f"  {src:<8} {n:>4} 条")
    works = Counter(r["anime_name"] for r in records)
    for w, n in sorted(works.items()):
        print(f"    {w:<24} {n:>4} 条")

    print("\n========== Film 步骤2/4 生成清洗字段 ==========")
    for i, r in enumerate(records, start=1):
        raw = r["content"]
        content = clean_text(raw)
        r["record_id"] = f"REC{i:05d}"
        r["content_raw"] = raw
        r["content_clean"] = content
        r["content_length"] = len(content)
        r["lang"] = detect_lang(content)
        r["noise_list"] = []
        r["is_relevant"] = True
        r["noise_reason"] = ""
        r["duplicate_flag"] = 0

    print("\n========== Film 步骤3/4 去重标记 ==========")
    seen_id = set()
    seen_fallback = set()
    dup_count = 0
    for r in records:
        cid = r["comment_id"]
        if cid:
            key = ("id", r["source"], cid)
            bucket = seen_id
        else:
            norm = normalized(r["content_clean"])
            digest = hashlib.sha1(norm.encode("utf-8")).hexdigest()
            key = ("fb", r["source"], r["page_url"], r["author"],
                   r["post_time"], digest)
            bucket = seen_fallback
        if key in bucket:
            r["duplicate_flag"] = 1
            dup_count += 1
        else:
            bucket.add(key)
    print(f"去重标记: {dup_count} 条重复记录")

    print("\n========== Film 步骤4/4 噪音标记 ==========")
    seen_norm = {}
    for r in records:
        norm = normalized(r["content_clean"])
        if len(norm) >= 4:
            if norm in seen_norm:
                r["noise_list"].append("duplicate_text")
            else:
                seen_norm[norm] = r["record_id"]

    for r in records:
        r["noise_list"].extend(detect_noise(r))
        r["noise_list"] = sorted(set(r["noise_list"]))
        if r["noise_list"]:
            r["noise_reason"] = ";".join(r["noise_list"])
            r["is_relevant"] = False
        if r["duplicate_flag"]:
            r["is_relevant"] = False

    # ==================== 5. 输出 ====================
    base_cols = [c for c in BASE_COLS if c != "content"]
    raw_cols = ["record_id"] + base_cols + ["form", "content_raw", "content_clean",
                                            "lang", "content_length"]
    all_cols = raw_cols + ["is_relevant", "noise_reason", "duplicate_flag"]

    with open(OUT_RAW, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=raw_cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(records)

    with open(OUT_ALL, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=all_cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(records)

    valid = [r for r in records if r["is_relevant"]]
    with open(OUT_VALID, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=all_cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(valid)

    print(f"\n输出: {OUT_RAW.name}  ({len(records)} 条)")
    print(f"输出: {OUT_ALL.name}  ({len(records)} 条)")
    print(f"输出: {OUT_VALID.name}  ({len(valid)} 条有效)")

    # ==================== 6. 审计报表 ====================
    build_audit(records, valid, dup_count)

    # ==================== 7. 控制台汇总 ====================
    noise_counter = Counter()
    for r in records:
        for n in r["noise_list"]:
            noise_counter[n] += 1

    print("\n================ Film 清洗前后汇总 ================")
    print(f"清洗前总条数      : {len(records)}")
    print(f"去重数量          : {dup_count}")
    print(f"清洗后(去重后)     : {len(records) - dup_count}")
    print(f"有效样本数量      : {len(valid)}")
    print(f"被标记噪音记录    : {sum(1 for r in records if r['noise_list'])}")
    print("\n各平台:")
    for src in ["RT", "X", "YouTube", "Reddit", "AniList", "MAL"]:
        before = sum(1 for r in records if r["source"] == src)
        after = sum(1 for r in valid if r["source"] == src)
        print(f"  {src:<8} 清洗前 {before:>4}  ->  有效 {after:>4}")
    print("\n各作品:")
    for w in sorted(works):
        before = sum(1 for r in records if r["anime_name"] == w)
        after = sum(1 for r in valid if r["anime_name"] == w)
        print(f"  {w:<24} 清洗前 {before:>4}  ->  有效 {after:>4}")
    print("\n噪音分类:")
    for name, cnt in noise_counter.most_common():
        print(f"  {name:<20} {cnt}")
    print(f"\n审计报表已写入: {OUT_AUDIT.name}")


def build_audit(records, valid, dup_count):
    """生成 cleaning_audit.xlsx。"""
    noise_counter = Counter()
    for r in records:
        for n in r["noise_list"]:
            noise_counter[n] += 1

    overview = pd.DataFrame({
        "指标": ["清洗前总条数", "去重数量", "清洗后(去重后)", "有效样本数量",
                 "被标记噪音记录数", "噪音标记总次数", "生成时间"],
        "数值": [len(records), dup_count, len(records) - dup_count, len(valid),
                 sum(1 for r in records if r["noise_list"]),
                 sum(noise_counter.values()),
                 datetime.now().isoformat(timespec="seconds")],
    })

    srcs = ["RT", "X", "YouTube", "Reddit", "AniList", "MAL"]
    plat = [{
        "平台": src,
        "清洗前": sum(1 for r in records if r["source"] == src),
        "去重": sum(1 for r in records if r["source"] == src and r["duplicate_flag"]),
        "有效": sum(1 for r in valid if r["source"] == src),
    } for src in srcs]
    plat_df = pd.DataFrame(plat)

    works = sorted({r["anime_name"] for r in records})
    work_rows = [{
        "作品": w,
        "清洗前": sum(1 for r in records if r["anime_name"] == w),
        "去重": sum(1 for r in records if r["anime_name"] == w and r["duplicate_flag"]),
        "有效": sum(1 for r in valid if r["anime_name"] == w),
    } for w in works]
    work_df = pd.DataFrame(work_rows)

    noise_df = pd.DataFrame([
        {"噪音类型": k, "条数": v} for k, v in noise_counter.most_common()
    ])

    sample_rows = []
    per_type = Counter()
    for r in records:
        for n in r["noise_list"]:
            if per_type[n] >= 5:
                continue
            per_type[n] += 1
            sample_rows.append({
                "record_id": r["record_id"],
                "噪音类型": n,
                "平台": r["source"],
                "作品": r["anime_name"],
                "作者": r["author"],
                "page_url": r["page_url"],
                "正文摘要": r["content_raw"][:120],
            })
    sample_df = pd.DataFrame(sample_rows)

    with pd.ExcelWriter(OUT_AUDIT, engine="openpyxl") as writer:
        overview.to_excel(writer, sheet_name="总览", index=False)
        plat_df.to_excel(writer, sheet_name="分平台", index=False)
        work_df.to_excel(writer, sheet_name="分作品", index=False)
        noise_df.to_excel(writer, sheet_name="噪音明细", index=False)
        sample_df.to_excel(writer, sheet_name="待复核样例", index=False)


if __name__ == "__main__":
    try:
        import sys
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
