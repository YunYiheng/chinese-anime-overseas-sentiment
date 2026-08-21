"""
分析模板 —— 实习生 B 使用（Cross EDA + 关联分析）

============================================================
【必读】先看 README.md 和 docs/DATA_SPEC.md。
  输入数据：storage/05主题分析/05_topic_labeled.csv（54 列，4 平台）
  关键字段：source / anime_name / sentiment_final / topic_* 布尔列
============================================================

【方法约定】
  - 情感统一用 sentiment_final（不要用 sentiment_pred，那个会高估负面）。
  - 统计基数通常排除 sentiment_final == "other"（非明确情感）。
  - 主题是【多标签】：一条评论可以命中多个主题（topic_count 可 >1），
    所以「主题 × 平台 / 主题 × 情感」不是互斥交叉表，用命中率/命中次数画图。
  - 「平台 × 情感」「作品 × 情感」是互斥的（每条评论一个情感），可做卡方检验。

【输出】
  figures/ 下的 PNG + association_results.csv（字段见 run_association）
"""
import sys
import os
import pandas as pd
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from scipy import stats

# === 中文字体（Windows） ===
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

# === 统一配色 ===
SENTIMENT_ORDER = ["positive", "neutral", "negative", "mixed"]
SENTIMENT_COLORS = {
    "positive": "#2e7d32",
    "neutral": "#9e9e9e",
    "negative": "#c62828",
    "mixed": "#ef6c00",
    "other": "#bdbdbd",
}
PLATFORM_ORDER = ["Reddit", "AniList", "YouTube", "X", "MAL"]  # 按需调整

# 12 个主题列名（多标签布尔列）
TOPIC_COLS = [
    "topic_story_plot", "topic_worldbuilding", "topic_character",
    "topic_animation_visual", "topic_action_fight", "topic_pacing_length",
    "topic_music_voice", "topic_chinese_culture", "topic_subtitle_locale",
    "topic_release_availability", "topic_awareness_marketing", "topic_ip_derivative",
]
# 主题中文短名（画图用）
TOPIC_SHORT = {
    "topic_story_plot": "剧情", "topic_worldbuilding": "世界观",
    "topic_character": "角色", "topic_animation_visual": "画面动画",
    "topic_action_fight": "动作战斗", "topic_pacing_length": "节奏时长",
    "topic_music_voice": "音乐配音", "topic_chinese_culture": "中国文化",
    "topic_subtitle_locale": "字幕本地化", "topic_release_availability": "海外发行",
    "topic_awareness_marketing": "传播知名度", "topic_ip_derivative": "IP衍生",
}


def load_data(path="storage/05主题分析/05_topic_labeled.csv"):
    """读分析级数据，并默认排除 other 情感。"""
    df = pd.read_csv(path, encoding="utf-8-sig")
    df = df[df["sentiment_final"] != "other"].copy()
    return df


def ensure_dir(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)


# ============================================================
# 一、Cross EDA：画图函数（全部写成 plot_xxx(df) 形式，读 df 不写死 CSV）
# ============================================================
def plot_platform_sentiment(df, save_path="figures/platform_sentiment.png"):
    """平台 × 情感：stacked bar（百分比）。"""
    ct = pd.crosstab(df["source"], df["sentiment_final"])
    ct = ct.reindex(columns=[c for c in SENTIMENT_ORDER if c in ct.columns])
    pct = ct.div(ct.sum(axis=1), axis=0) * 100

    fig, ax = plt.subplots(figsize=(9, 5))
    bottom = np.zeros(len(pct))
    for col in pct.columns:
        ax.bar(pct.index, pct[col], bottom=bottom,
               color=SENTIMENT_COLORS.get(col, "#999"), label=col)
        bottom += pct[col].values
    ax.set_ylabel("占比 (%)")
    ax.set_title("平台 × 情感分布")
    ax.legend(title="情感")
    ax.grid(axis="y", alpha=0.3)
    ensure_dir(save_path)
    fig.tight_layout()
    fig.savefig(save_path, dpi=150)
    plt.close(fig)
    print(f"  已保存 {save_path}")
    return ct


def plot_anime_sentiment(df, save_path="figures/anime_sentiment.png"):
    """作品 × 情感：stacked bar（百分比）。结构同上。"""
    # 【TODO】参照 plot_platform_sentiment，把 df['source'] 换成 df['anime_name']
    raise NotImplementedError("TODO: 参照 plot_platform_sentiment 实现")


def plot_platform_topic(df, save_path="figures/platform_topic.png"):
    """平台 × 主题：每个平台里各主题的命中率（多标签，不是互斥）。"""
    # 每个平台各主题命中数 / 该平台评论数
    rows = []
    for src, g in df.groupby("source"):
        n = len(g)
        for col in TOPIC_COLS:
            rows.append({"platform": src, "topic": TOPIC_SHORT[col],
                         "hit_rate": g[col].mean() * 100})
    tr = pd.DataFrame(rows)
    heat = tr.pivot(index="platform", columns="topic", values="hit_rate")

    fig, ax = plt.subplots(figsize=(12, 5))
    im = ax.imshow(heat.to_numpy(dtype=float), aspect="auto",
                   cmap=matplotlib.colormaps["Blues"])
    ax.set_xticks(range(len(heat.columns)))
    ax.set_xticklabels(heat.columns, rotation=45, ha="right")
    ax.set_yticks(range(len(heat.index)))
    ax.set_yticklabels(heat.index)
    fig.colorbar(im, ax=ax, label="命中率 (%)")
    ax.set_title("平台 × 主题命中率")
    ensure_dir(save_path)
    fig.tight_layout()
    fig.savefig(save_path, dpi=150)
    plt.close(fig)
    print(f"  已保存 {save_path}")
    return heat


def plot_topic_sentiment(df, save_path="figures/topic_sentiment.png"):
    """主题 × 情感：命中某主题的评论里，情感分布（百分比）。"""
    # 【TODO】对每个主题，筛出命中该主题的评论，统计 sentiment_final 分布，
    #        画 stacked bar 或 heatmap。
    raise NotImplementedError("TODO: 实现 主题×情感")


# ============================================================
# 二、关联分析：CrossTab → χ² → Cramér's V → 标准化残差
# ============================================================
def cramers_v(chi2, n, r, k):
    """Cramér's V 效应量。r/k 是交叉表的行/列数。"""
    denom = n * (min(r, k) - 1)
    if denom == 0:
        return np.nan
    return float(np.sqrt(chi2 / denom))


def strength_label(v):
    if v < 0.1:
        return "negligible"
    if v < 0.3:
        return "weak"
    if v < 0.5:
        return "moderate"
    return "strong"


def standardized_residual(observed):
    """标准化残差 = (O - E) / sqrt(E)。越大表示该格偏离越显著。"""
    observed = observed.to_numpy(dtype=float)
    row_sums = observed.sum(axis=1, keepdims=True)
    col_sums = observed.sum(axis=0, keepdims=True)
    total = observed.sum()
    expected = row_sums @ col_sums / total
    with np.errstate(divide="ignore", invalid="ignore"):
        residual = (observed - expected) / np.sqrt(expected)
    return residual


def association_analysis(df, x, y):
    """对两个分类变量做卡方 + Cramér's V，返回一行结果 dict。"""
    ct = pd.crosstab(df[x], df[y])
    chi2, p, dof, expected = stats.chi2_contingency(ct)
    n = ct.to_numpy().sum()
    v = cramers_v(chi2, n, ct.shape[0], ct.shape[1])
    return {
        "variable_x": x,
        "variable_y": y,
        "chi2": round(chi2, 4),
        "dof": dof,
        "p_value": round(p, 6),
        "cramers_v": round(v, 4),
        "strength": strength_label(v),
        "n": int(n),
    }, ct


def plot_residual(ct, save_path):
    """标准化残差 heatmap。"""
    res = standardized_residual(ct)
    fig, ax = plt.subplots(figsize=(8, 5))
    vmax = np.nanmax(np.abs(res)) if np.isfinite(res).any() else 1
    im = ax.imshow(res, cmap=matplotlib.colormaps["RdBu_r"],
                   vmin=-vmax, vmax=vmax, aspect="auto")
    ax.set_xticks(range(ct.shape[1])); ax.set_xticklabels(ct.columns, rotation=45, ha="right")
    ax.set_yticks(range(ct.shape[0])); ax.set_yticklabels(ct.index)
    fig.colorbar(im, ax=ax, label="标准化残差")
    ensure_dir(save_path)
    fig.tight_layout()
    fig.savefig(save_path, dpi=150)
    plt.close(fig)
    print(f"  已保存 {save_path}")


def run_association(df):
    """跑 4 组关联分析，输出 association_results.csv + 残差图。"""
    pairs = [
        ("source", "sentiment_final", "figures/platform_sentiment_residual.png"),
        ("anime_name", "sentiment_final", "figures/anime_sentiment_residual.png"),
        # 主题是多标签，先做「命中剧情 vs 未命中」这类 2×情感，或把 topic 拆成行
        # 【TODO】Platform×Topic / Topic×Sentiment 用合适的构造方式补上
    ]
    results = []
    for x, y, fig_path in pairs:
        row, ct = association_analysis(df, x, y)
        results.append(row)
        plot_residual(ct, fig_path)

    out = pd.DataFrame(results)
    out.to_csv("association_results.csv", index=False, encoding="utf-8-sig")
    print("\n关联分析结果已保存 → association_results.csv")
    print(out.to_string(index=False))
    return out


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    df = load_data()
    print(f"加载 {len(df)} 条（已排除 other）")

    # Cross EDA
    plot_platform_sentiment(df)
    plot_platform_topic(df)
    # 【TODO】补 plot_anime_sentiment / plot_anime_topic / plot_topic_sentiment

    # 关联分析
    run_association(df)
