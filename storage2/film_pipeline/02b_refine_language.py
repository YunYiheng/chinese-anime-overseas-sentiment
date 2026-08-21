# -*- coding: utf-8 -*-
"""
02b_refine_language.py —— 语言细分（langdetect，seed 固定可复现）

说明: 不改 01_merge_clean.py，不覆盖原 lang 字段。只在 02_cleaned_valid.csv 基础上加 4 列：
  lang_original    原启发式 lang 的备份（保留核查）
  lang_detected    langdetect 判定的语言代码（en/zh/es/...），弱置信标 unknown，明显中英混标 mixed
  lang_confidence  该判定的置信度（unknown/mixed 为 0）
  lang_group       语言分组名（中文/英语/...），用于统计与画图

规则（按需求 + 实测修正）:
  - DetectorFactory.seed = 0 保证可复现
  - 文本过短 / 有效字母不足 / detect_langs 最高概率 < 0.80 -> unknown
  - 明显中英混合（汉字>=5 且 拉丁字母>=15）-> mixed
  - 【实测修正】langdetect 对中文极不可靠（纯中文被判成 ko，带英文被判成 en）：
    汉字占有效字母比例 >= 0.4 且无日文假名/韩文谚文 -> 直接判 zh
  - 不删除任何样本；不根据语言推断国家或用户国籍

输出:
  02_cleaned_valid_lang.csv          新增 4 列后的完整数据
  eda_language_refined.xlsx          细分语言统计表（5 张表）
  language_refined_distribution.png  新版语言分布图（低频语言合并为"其他语言"）
"""
import re
import sys
from collections import Counter

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

from langdetect import DetectorFactory, detect_langs
from langdetect.lang_detect_exception import LangDetectException

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial"]
plt.rcParams["axes.unicode_minus"] = False

DetectorFactory.seed = 0   # 可复现

INPUT = "02_cleaned_valid.csv"
OUT_CSV = "02_cleaned_valid_lang.csv"
OUT_XLSX = "eda_language_refined.xlsx"
OUT_PNG = "language_refined_distribution.png"

# ---- 判定阈值 ----
MIN_LETTERS = 4      # 有效字母下限，低于则 unknown（过短/无实质内容）
MIN_PROB = 0.80      # detect_langs 最高概率下限，低于则 unknown
CJK_RATIO = 0.40     # 汉字占有效字母比例下限，达到且无假名/谚文则直接判 zh
MIX_CJK = 5          # 中英混合：汉字至少 5 个
MIX_LATIN = 15       # 中英混合：拉丁字母至少 15 个

# ---- 分组显示名（用于统计表与图）----
GROUP_NAMES = {
    "zh": "中文", "en": "英语", "es": "西班牙语", "ja": "日语", "ko": "韩语",
    "fr": "法语", "pt": "葡萄牙语", "de": "德语", "ru": "俄语", "it": "意大利语",
    "id": "印尼语", "vi": "越南语", "th": "泰语", "ar": "阿拉伯语", "nl": "荷兰语",
    "pl": "波兰语", "tr": "土耳其语", "sv": "瑞典语", "hi": "印地语", "tl": "他加禄语",
    "cs": "捷克语", "uk": "乌克兰语", "el": "希腊语", "ro": "罗马尼亚语",
    "ms": "马来语", "da": "丹麦语", "fi": "芬兰语", "hu": "匈牙利语", "no": "挪威语",
}
LANG_NORM = {"zh-cn": "zh", "zh-tw": "zh"}   # langdetect 的中文两种变体统一为 zh

CJK_RE = re.compile(r"[㐀-鿿]")
KANA_RE = re.compile(r"[぀-ヿ]")
HANGUL_RE = re.compile(r"[가-힯]")
LATIN_RE = re.compile(r"[A-Za-z]")


def classify(content: str):
    """返回 (lang_detected, confidence)。不删除、不推断国籍。"""
    if not content:
        return "unknown", 0.0

    # 去掉 @提及 和 #话题，避免干扰语言判定（也不计入"有效字母"）
    text = re.sub(r"[@#]\w+", " ", content)

    total_letters = len(re.findall(r"[^\W\d_]", text))
    if total_letters < MIN_LETTERS:
        return "unknown", 0.0

    cjk = len(CJK_RE.findall(text))
    kana = len(KANA_RE.findall(text))
    hangul = len(HANGUL_RE.findall(text))
    latin = len(LATIN_RE.findall(text))

    # 中文兜底（langdetect 对中文不可靠）
    if cjk > 0 and kana == 0 and hangul == 0 and cjk / total_letters >= CJK_RATIO:
        return "zh", round(cjk / total_letters, 3)

    # 明显中英混合
    if cjk >= MIX_CJK and latin >= MIX_LATIN:
        return "mixed", 0.0

    try:
        langs = detect_langs(text)
    except LangDetectException:
        return "unknown", 0.0

    top = langs[0]
    if top.prob < MIN_PROB:
        return "unknown", round(top.prob, 3)
    return LANG_NORM.get(top.lang, top.lang), round(top.prob, 3)


def pct(c, total):
    return f"{c} ({c / total * 100:.1f}%)" if total else "0 (0.0%)"


def main():
    df = pd.read_csv(INPUT, encoding="utf-8-sig")
    total = len(df)

    # 1) 备份原 lang 字段
    df["lang_original"] = df["lang"]

    # 2) 逐条判定
    results = [classify(x) for x in df["content_clean"].fillna("")]
    df["lang_detected"] = [r[0] for r in results]
    df["lang_confidence"] = [r[1] for r in results]
    df["lang_group"] = df["lang_detected"].map(lambda c: GROUP_NAMES.get(c, c))
    df.loc[df["lang_detected"] == "unknown", "lang_group"] = "未知"
    df.loc[df["lang_detected"] == "mixed", "lang_group"] = "中英混合"

    # 3) 输出完整 CSV（utf-8-sig，原列全保留 + 新 4 列）
    df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    print(f"[完成] {OUT_CSV}（{total} 行，新增 lang_original/lang_detected/lang_confidence/lang_group）")

    # 4) 统计
    det = Counter(df["lang_detected"])
    grp = Counter(df["lang_group"])
    det_df = pd.DataFrame({
        "语言": [k for k, v in det.most_common()],
        "条数": [v for _, v in det.most_common()],
        "占比": [pct(v, total) for _, v in det.most_common()],
    })
    grp_df = pd.DataFrame({
        "分组": [k for k, v in grp.most_common()],
        "条数": [v for _, v in grp.most_common()],
        "占比": [pct(v, total) for _, v in grp.most_common()],
    })

    # 原 en/zh 桶细分成了什么（核查用）
    orig_new = pd.crosstab(df["lang_original"], df["lang_detected"])
    orig_new = orig_new.reset_index().rename(columns={"lang_original": "原lang"})
    plat_grp = pd.crosstab(df["source"], df["lang_group"])
    plat_grp["合计"] = plat_grp.sum(axis=1)
    plat_grp = plat_grp.reset_index().rename(columns={"source": "平台"})

    # 未知/混合样本（供人工核查）
    unclear = df[df["lang_detected"].isin(["unknown", "mixed"])].copy()
    unclear["正文摘要"] = unclear["content_raw"].str[:80]
    unclear = unclear[["record_id", "source", "anime_name", "lang_original",
                       "lang_detected", "lang_confidence", "正文摘要"]]

    with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as w:
        det_df.to_excel(w, sheet_name="语言细分", index=False)
        grp_df.to_excel(w, sheet_name="语言分组", index=False)
        orig_new.to_excel(w, sheet_name="原vs新", index=False)
        plat_grp.to_excel(w, sheet_name="平台×语言分组", index=False)
        unclear.to_excel(w, sheet_name="未知与混合样本", index=False)
    print(f"[完成] {OUT_XLSX}（5 张表，未知/混合 {len(unclear)} 条待核查）")

    # 5) 新版语言分布图（低频合并为"其他语言"）
    threshold = max(10, int(total * 0.02))
    keep, merged = {}, {}
    for k, v in grp.most_common():
        if v >= threshold or k in ("未知", "中英混合"):
            keep[k] = v
        else:
            merged[k] = v
    if merged:
        keep["其他语言"] = sum(merged.values())

    fig, ax = plt.subplots(figsize=(11, 5.5))
    keys = list(keep.keys())
    vals = list(keep.values())
    colors = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3",
              "#937860", "#DA8BC3", "#8C8C8C", "#CCB974", "#64B5CD"]
    if "其他语言" in keys:
        colors[keys.index("其他语言")] = "#9E9E9E"
    bars = ax.bar(range(len(keys)), vals, color=colors[:len(keys)])
    ax.set_xticks(range(len(keys)))
    ax.set_xticklabels(keys, rotation=25, ha="right")
    ax.set_title("语言细分分布（低频语言已合并为\"其他语言\"）")
    ax.set_ylabel("条数")
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v, str(v),
                ha="center", va="bottom", fontsize=9)
    fig.tight_layout()
    fig.savefig(OUT_PNG, dpi=150)
    plt.close(fig)
    print(f"[完成] {OUT_PNG}")

    # 6) 控制台摘要
    print("\n================ 语言细分结果 ================")
    print(f"总样本: {total}")
    print("细分语言 top:")
    for k, v in det.most_common():
        print(f"  {k:<6} {v:>4} 条  {v/total*100:.1f}%")
    merged_names = "、".join(f"{k}({v})" for k, v in merged.items())
    if merged_names:
        print(f"低频合并为\"其他语言\": {merged_names}")
    unknown = det.get("unknown", 0)
    mixed = det.get("mixed", 0)
    print(f"\nunknown（置信不足/过短）: {unknown}，中英混合: {mixed}")
    # 原 en 桶被细分出多少其他语言
    en_refined = df[(df["lang_original"] == "en") &
                    (df["lang_detected"] != "en")]
    print(f"原 en 桶中被细分出的非英语样本: {len(en_refined)} 条")


if __name__ == "__main__":
    main()
