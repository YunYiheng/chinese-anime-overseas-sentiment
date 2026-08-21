# -*- coding: utf-8 -*-
"""
08 最终报告图表生成 —— 产出 7 张新图（旧 Phase-2 前混合口径图全部废弃，不得复用）

输出（根目录）：
  一级必做：
    cover_matrix.png           作品×平台覆盖矩阵（格内写样本数，浅色标注未准入格子）
    series_platform_dist.png   Series 平台分布
    film_platform_dist.png     Film 平台分布
    series_sentiment_dist.png  Series 三口径情感分布
    film_sentiment_dist.png    Film 三口径情感分布
  二级（篇幅不足放附录）：
    series_time_dist.png       Series 时间分布（年月）
    film_time_dist.png         Film 时间分布（年月，RT 无年份条目除外）

口径约束（与 analysis_validation_summary.md 一致）：
  - 平台准入：n>=30 且 覆盖作品>=3（Series 准入 MAL/Reddit/X/YouTube；Film 准入 RT/X/YouTube）
  - 情感三口径：platform_balanced 主 / pooled 附注 / all_platform_equal 仅敏感性
  - 情感分布一律排除 other
"""
import sys
import re
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.patches import Rectangle

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial"]
plt.rcParams["axes.unicode_minus"] = False

SERIES = pd.read_csv("analytical_series.csv", encoding="utf-8-sig")
FILM = pd.read_csv("analytical_film.csv", encoding="utf-8-sig")
ALL = pd.read_csv("analytical_all.csv", encoding="utf-8-sig")

SERIES_WORKS = ["Link Click", "Scissor Seven", "Ling Cage", "Soul Land", "RMJI", "BTTH"]
FILM_WORKS = ["Ne Zha", "Ne Zha 2", "White Snake", "Jiang Ziya",
              "New Gods: Nezha Reborn", "I Am What I Am", "New Gods: Yang Jian"]
PLATFORMS = ["Reddit", "YouTube", "X", "MAL", "AniList", "RT"]
PLATFORM_CN = {
    "Reddit": "Reddit", "YouTube": "YouTube", "X": "X",
    "MAL": "MyAnimeList", "AniList": "AniList", "RT": "Rotten Tomatoes",
}

# 准入平台（form -> 准入集合），与 04/07 完全一致
ADMITTED = {
    "series": {"Reddit", "YouTube", "X", "MAL"},
    "film": {"RT", "X", "YouTube"},
}

SENT_CN = {"positive": "正面", "neutral": "中性", "mixed": "混合", "negative": "负面"}
SENT_COLORS = {"positive": "#2e7d32", "neutral": "#90a4ae", "mixed": "#f9a825", "negative": "#c62828"}
KOUJING_COLORS = {"pooled": "#b0bec5", "platform_balanced": "#1565c0", "all_platform_equal": "#bbdefb"}


# ---------------------------------------------------------------- 覆盖矩阵
def gen_cover_matrix():
    works = SERIES_WORKS + FILM_WORKS
    n_rows = len(works)
    n_cols = len(PLATFORMS)

    mat = np.zeros((n_rows, n_cols), dtype=int)
    for i, w in enumerate(works):
        for j, p in enumerate(PLATFORMS):
            mat[i, j] = int(((ALL["anime_name"] == w) & (ALL["source"] == p)).sum())

    fig, ax = plt.subplots(figsize=(12.5, 9.5))
    vmax = max(10, int(mat.max()))
    cm = matplotlib.colormaps["YlGnBu"]
    norm = mcolors.Normalize(vmin=0, vmax=vmax)
    ax.imshow(mat, cmap=cm, norm=norm, aspect="auto")

    # 行列标签
    ax.set_xticks(range(n_cols))
    ax.set_xticklabels([PLATFORM_CN[p] for p in PLATFORMS], rotation=25, ha="right", fontsize=9.5)
    ax.set_yticks(range(n_rows))
    ax.set_yticklabels(works, fontsize=9)

    # 分界线：Series / Film
    ax.axhline(5.5, color="#555", lw=1.2, ls="-")
    ax.text(-0.85, 2.5, "Series\n（系列动画）", fontsize=10, weight="bold",
            ha="right", va="center", color="#0d47a1")
    ax.text(-0.85, 9.5, "Film\n（动画电影）", fontsize=10, weight="bold",
            ha="right", va="center", color="#b71c1c")

    # 单元格：写样本数；未准入格子浅色覆盖 + †；空值写 —；小样本(n<30)标 *
    for i, w in enumerate(works):
        form = "series" if w in SERIES_WORKS else "film"
        for j, p in enumerate(PLATFORMS):
            v = mat[i, j]
            admitted = p in ADMITTED[form]
            if v == 0:
                ax.text(j, i, "—", ha="center", va="center", fontsize=9, color="#9e9e9e")
                continue
            # 未准入格子：浅色覆盖
            if not admitted:
                ax.add_patch(Rectangle((j - 0.5, i - 0.5), 1, 1, fill=True,
                                       facecolor="white", alpha=0.55, edgecolor="none"))
            # 文本颜色：深色格子用白字
            txt_color = "white" if v > vmax * 0.55 else "#333"
            label = str(v) if admitted else f"{v}†"
            ax.text(j, i, label, ha="center", va="center", fontsize=9.5,
                    color=txt_color, weight="bold")

    ax.set_xticks(np.arange(-0.5, n_cols, 1), minor=True)
    ax.set_yticks(np.arange(-0.5, n_rows, 1), minor=True)
    ax.grid(which="minor", color="white", lw=1)
    ax.tick_params(which="minor", length=0)
    ax.tick_params(which="major", length=0)

    ax.set_title("作品 × 平台 评论覆盖矩阵（格内为样本数）", fontsize=13, weight="bold", pad=14)
    fig.text(0.02, 0.012,
             "† = 该平台在此层未纳入正式推断（n<30 或 覆盖作品<3），仅作展示。"
             "Series 准入 MAL/Reddit/X/YouTube；Film 准入 RT/X/YouTube。",
             fontsize=8.5, color="#555", ha="left")

    fig.tight_layout(rect=[0.0, 0.04, 1, 1])
    fig.savefig("cover_matrix.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("[OK] cover_matrix.png")


# ---------------------------------------------------------------- 平台分布
def gen_platform_dist():
    for form, df, outname in [
        ("series", SERIES, "series_platform_dist.png"),
        ("film", FILM, "film_platform_dist.png"),
    ]:
        main = df[df["sentiment_final"] != "other"]
        counts = {p: int((main["source"] == p).sum()) for p in PLATFORMS}
        # 只保留该层有数据的平台，按样本量降序
        platforms = [p for p in PLATFORMS if counts[p] > 0]
        platforms = sorted(platforms, key=lambda p: -counts[p])
        vals = [counts[p] for p in platforms]
        colors = ["#1565c0" if p in ADMITTED[form] else "#cfd8dc" for p in platforms]

        fig, ax = plt.subplots(figsize=(9, 4.5))
        bars = ax.barh(platforms, vals, color=colors)
        for b, v, p in zip(bars, vals, platforms):
            ax.text(v + max(vals) * 0.01, b.get_y() + b.get_height() / 2,
                    f"{v:,}", va="center", fontsize=9.5, weight="bold")
        title = "Series 各平台主样本量（排除 other）" if form == "series" else "Film 各平台主样本量（排除 other）"
        ax.set_title(title, fontsize=13, weight="bold", pad=12)
        ax.set_xlabel("评论数（主样本，排除 other）", fontsize=10)
        ax.invert_yaxis()
        ax.spines[["top", "right"]].set_visible(False)

        # 图例：准入 / 未准入
        from matplotlib.patches import Patch
        handles = [Patch(color="#1565c0", label="正式准入平台（n≥30 且 覆盖≥3）"),
                   Patch(color="#cfd8dc", label="未准入（仅展示）")]
        ax.legend(handles=handles, loc="lower right", fontsize=8.5, frameon=False)

        fig.tight_layout()
        fig.savefig(outname, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"[OK] {outname}  ->  {dict(zip(platforms, vals))}")


# ---------------------------------------------------------------- 三口径情感分布
def _read_sankoujing(path):
    """读 xlsx「三口径对比」sheet，返回 {情感: {口径: 百分比}}"""
    df = pd.read_excel(path, sheet_name="三口径对比", header=1)
    df.columns = [str(c).strip() for c in df.columns]
    df = df[df["情感"].notna()].copy()
    col_pooled = [c for c in df.columns if c.startswith("pooled")][0]
    col_balanced = [c for c in df.columns if c.startswith("platform_balanced")][0]
    col_all_equal = [c for c in df.columns if c.startswith("all_platform_equal")][0]
    out = {}
    for _, row in df.iterrows():
        sent = str(row["情感"]).strip()
        out[sent] = {
            "pooled": float(row[col_pooled]),
            "platform_balanced": float(row[col_balanced]),
            "all_platform_equal": float(row[col_all_equal]),
        }
    return out


def gen_sentiment_dist():
    specs = [
        ("series", "storage2/series_pipeline/series_sentiment_final_summary.xlsx",
         "series_sentiment_dist.png", "Series 三口径情感分布（%）"),
        ("film", "storage2/film_pipeline/film_sentiment_final_summary.xlsx",
         "film_sentiment_dist.png", "Film 三口径情感分布（%）"),
    ]
    for form, xlsx, outname, title in specs:
        data = _read_sankoujing(xlsx)
        sents = ["positive", "neutral", "mixed", "negative"]
        koujings = ["pooled", "platform_balanced", "all_platform_equal"]
        k_cn = {"pooled": "pooled\n（汇总）", "platform_balanced": "platform_balanced\n（正文主口径）",
                "all_platform_equal": "all_platform_equal\n（敏感性）"}

        x = np.arange(len(sents))
        width = 0.26
        fig, ax = plt.subplots(figsize=(10, 5.2))
        for ki, k in enumerate(koujings):
            vals = [data[s][k] for s in sents]
            off = (ki - 1) * width
            bars = ax.bar(x + off, vals, width, color=KOUJING_COLORS[k], label=k_cn[k])
            for b, v in zip(bars, vals):
                ax.text(b.get_x() + b.get_width() / 2, v + 0.5, f"{v:.1f}",
                        ha="center", va="bottom", fontsize=8.2,
                        weight="bold" if k == "platform_balanced" else "normal")

        ax.set_xticks(x)
        ax.set_xticklabels([SENT_CN[s] for s in sents], fontsize=10)
        ax.set_ylabel("占比（%）", fontsize=10)
        ax.set_ylim(0, 82)
        ax.set_title(title, fontsize=13, weight="bold", pad=12)
        ax.legend(fontsize=8.5, loc="upper right", frameon=False)
        ax.spines[["top", "right"]].set_visible(False)
        fig.text(0.02, 0.012, "platform_balanced（深蓝）为正文主口径；pooled 附注实际抓取结构；all_platform_equal 仅敏感性，正文不引。",
                 fontsize=8.5, color="#555")
        fig.tight_layout(rect=[0, 0.04, 1, 1])
        fig.savefig(outname, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"[OK] {outname}")


# ---------------------------------------------------------------- 时间分布
def parse_year_month(s):
    if pd.isna(s):
        return None
    s = str(s).strip()
    m = re.match(r"(\d{4})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)  # "08/13/2025" (RT MM/DD/YYYY)
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}"
    m = re.search(r"([A-Za-z]{3,9})\s+\d{1,2},\s*(\d{4})", s)  # "Jul 9, 2021"
    if m:
        try:
            mon = pd.to_datetime(m.group(1) + " 1", format="%b %d").month
            return f"{m.group(2)}-{mon:02d}"
        except Exception:
            return None
    return None


def gen_time_dist():
    specs = [
        ("series", SERIES, "series_time_dist.png", "Series 评论发布时间分布（按年月）"),
        ("film", FILM, "film_time_dist.png", "Film 评论发布时间分布（按年月；RT 无年份条目除外）"),
    ]
    for form, df, outname, title in specs:
        ym = df["post_time"].apply(parse_year_month).dropna()
        vc = ym.value_counts().sort_index()
        # 只保留 2019 年之后（仅剔除 Series MAL 2018 的 3 条极早长尾）
        vc = vc[vc.index >= "2019-01"]

        fig, ax = plt.subplots(figsize=(11, 4.5))
        ax.bar(vc.index, vc.values, color="#1565c0", width=0.7)
        ax.set_title(title, fontsize=13, weight="bold", pad=12)
        ax.set_ylabel("评论数", fontsize=10)
        ax.set_xlabel("年-月", fontsize=10)
        # 月份标签稀疏化，避免密集重叠看不清
        step = max(1, len(vc) // 18)
        ticks = list(range(0, len(vc), step))
        ax.set_xticks(ticks)
        ax.set_xticklabels([vc.index[i] for i in ticks], rotation=45, fontsize=9)
        ax.tick_params(axis="x", length=0)
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout()
        fig.savefig(outname, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"[OK] {outname}  ->  {len(vc)} 个月份，共 {int(vc.sum())} 条（有年份）")


def main():
    print("开始生成最终报告图表 ...\n")
    gen_cover_matrix()
    gen_platform_dist()
    gen_sentiment_dist()
    gen_time_dist()
    print("\n全部图表生成完成。")


if __name__ == "__main__":
    main()
