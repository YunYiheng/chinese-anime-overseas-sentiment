# -*- coding: utf-8 -*-
"""
07 关联分析 —— 交叉表 → 卡方 → Cramér's V → 标准化残差
（读封版后的 analytical_series.csv / analytical_film.csv，不依赖原始管线）

研究问题：
  A. 不同海外平台如何评价中国系列动画？（Series：平台 × 情感）
  B. 同一批电影在不同海外社区舆情差异？（Film：平台 × 情感）
  C. Series vs Film 整体舆情差异？（work_form × 情感）
  D. 哪些主题在哪些平台被更多/更少提及？（12 主题 × 平台）

===== 两个统计坑（本项目已规避，务必保持）=====
坑1【稀疏表别硬跑卡方】：
  期望频数过小会让卡方 p 值失真。本脚本：
    - 平台准入：只有 n>=30 的平台才进卡方（AniList 27/1 条、Film-MAL 9 条等小样本单独列出，不进检验）；
    - 每次检验都打印"最小期望频数"，若 <5 的格子占比 >20% 会标 warning；
    - 另跑"正面率"（positive vs 非 positive）2×k 二值检验作稳健性对照（正面率 ~65%，格子充实，比 4 类更稳）。
坑2【主题多标签不能 explode 后做大卡方】：
  一条评论可命中多个主题，explode 会重复行、虚增样本量，且主题间不互斥。
  正确做法：12 个主题各自当独立 0/1 二值指标，分别与平台做 2×k 卡方，
  再 Bonferroni 多重比较校正（α=0.05/12≈0.00417）。

输出：
  07_association_results.xlsx（多 sheet）
  07_platform_sentiment_series.png / _film.png    平台×情感 堆叠柱状图
  07_residual_series.png / _film.png              标准化残差热力图
  07_topic_platform_series.png / _film.png        主题×平台 命中率热力图
"""
import sys
import numpy as np
import pandas as pd
from scipy import stats

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ============ 常量 ============
SENT_ORDER = ["positive", "neutral", "negative", "mixed"]  # "other" 排除出统计分母
PLATFORM_MIN_N = 30          # 平台进入卡方检验的最小样本量（有效评论，排除 other）
MIN_PLATFORM_WORKS = 3       # 平台覆盖作品数门槛（>=3 才准入，与 04 三口径一致）
ALPHA = 0.05

# 12 个主题（zh_label 与 topic_list 里一致，用于从 topic 字符串反推 0/1）
TOPICS = [
    ("story_plot", "剧情与叙事"),
    ("worldbuilding", "世界观与设定"),
    ("character", "角色塑造"),
    ("animation_visual", "画面与动画制作"),
    ("action_fight", "动作与战斗场面"),
    ("pacing_length", "节奏与时长"),
    ("music_voice", "音乐与配音"),
    ("chinese_culture", "中国文化表达"),
    ("subtitle_locale", "字幕与本地化"),
    ("release_availability", "海外发行与观看渠道"),
    ("awareness_marketing", "传播与知名度"),
    ("ip_derivative", "IP及衍生开发"),
]


# ============ 数据加载与预处理 ============
def load_data():
    s = pd.read_csv("analytical_series.csv", encoding="utf-8-sig")
    f = pd.read_csv("analytical_film.csv", encoding="utf-8-sig")
    for df in (s, f):
        # 从 topic 字符串反推 12 个主题的 0/1（zh_label 全短语、互不为子串，精确安全）
        for tid, zh in TOPICS:
            df["topic_" + tid] = df["topic"].astype(str).str.contains(zh, regex=False).astype(int)
    return s, f


# ============ 统计工具 ============
def adjusted_residuals(observed, expected):
    """调整后的标准化残差 z = (O-E)/sqrt(E*(1-r_i/n)*(1-c_j/n))。
    |z|>1.96 ≈ p<0.05；|z|>2.58 ≈ p<0.01；|z|>3 强关联。"""
    n = observed.values.sum()  # 标量（总样本量）
    row_m = observed.sum(axis=1).values.reshape(-1, 1)
    col_m = observed.sum(axis=0).values.reshape(1, -1)
    denom = np.sqrt(expected * (1 - row_m / n) * (1 - col_m / n))
    return (observed.values - expected) / denom


def cramers_v(chi2, n, r, c):
    """Cramér's V 效应量：<0.1 弱，0.1-0.3 中，>0.5 强。"""
    if n == 0 or min(r - 1, c - 1) == 0:
        return np.nan
    return float(np.sqrt(chi2 / (n * min(r - 1, c - 1))))


def run_chi2(ct):
    """对一个交叉表跑完整卡方检验，返回结果 dict。"""
    # ct 可能含全 0 行/列，先清理
    ct = ct.loc[(ct.sum(axis=1) > 0), (ct.sum(axis=0) > 0)]
    n = int(ct.values.sum())
    r, c = ct.shape
    chi2, p, dof, expected = stats.chi2_contingency(ct.values, correction=False)
    exp_df = pd.DataFrame(expected, index=ct.index, columns=ct.columns)
    min_exp = float(expected.min())
    n_cells = r * c
    sparse_ratio = float((expected < 5).sum() / n_cells)
    sparse_flag = sparse_ratio > 0.20
    res = adjusted_residuals(ct, expected)
    res_df = pd.DataFrame(res, index=ct.index, columns=ct.columns)
    return {
        "n": n, "chi2": chi2, "p": p, "dof": dof,
        "cramers_v": cramers_v(chi2, n, r, c),
        "min_expected": min_exp, "sparse_ratio": sparse_ratio, "sparse_flag": sparse_flag,
        "expected": exp_df, "residuals": res_df, "table": ct,
    }


def fmt_p(p):
    if p < 0.001:
        return "<0.001"
    return f"{p:.4f}"


def eligible_platforms(d):
    """平台准入：n>=30 且 覆盖作品数>=3（与 04 三口径规则一致）。返回 (准入列表, 排除列表)。"""
    eligible, excluded = [], []
    for src, g in d.groupby("source"):
        n = len(g)
        works = g["anime_name"].nunique()
        if n >= PLATFORM_MIN_N and works >= MIN_PLATFORM_WORKS:
            eligible.append(src)
        else:
            excluded.append(src)
    return eligible, excluded


# ============ 主分析 ============
def analyze_sentiment_platform(df, work_form, sheet_prefix):
    """平台 × 情感（排除 other）。返回结果列表用于汇总。"""
    d = df[df["sentiment_final"] != "other"].copy()
    n_other = int((df["sentiment_final"] == "other").sum())

    # 平台准入：n>=30 且 覆盖作品数>=3
    included, excluded = eligible_platforms(d)

    d_inc = d[d["source"].isin(included)]
    ct = pd.crosstab(d_inc["source"], d_inc["sentiment_final"])[SENT_ORDER]

    print(f"\n{'='*66}")
    print(f"[{work_form.upper()}] 平台 × 情感 关联检验")
    print(f"  排除 other：{n_other} 条；纳入平台：{included}；排除小样本/低覆盖：{excluded}")
    print(f"{'='*66}")
    print(ct)
    res = run_chi2(ct)
    print(f"\n  χ²={res['chi2']:.2f}, df={res['dof']}, p={fmt_p(res['p'])}")
    print(f"  Cramér's V={res['cramers_v']:.3f}")
    print(f"  最小期望频数={res['min_expected']:.2f}，期望<5的格子占比={res['sparse_ratio']*100:.0f}%"
          + ("  ⚠ 稀疏，p 值仅供参考" if res["sparse_flag"] else "  ✓ 期望频数充足"))
    print(f"\n  标准化残差（|z|>1.96 显著，正=该格偏多，负=偏少）：")
    print(res["residuals"].round(2))

    # 稳健性：正面率（positive vs 非 positive）二值 2×k 检验
    d_inc = d_inc.copy()
    d_inc["is_positive"] = (d_inc["sentiment_final"] == "positive").astype(int)
    ct_bin = pd.crosstab(d_inc["source"], d_inc["is_positive"])
    res_bin = run_chi2(ct_bin)
    print(f"\n  [稳健性] 正面率 × 平台：χ²={res_bin['chi2']:.2f}, p={fmt_p(res_bin['p'])}, V={res_bin['cramers_v']:.3f}")

    # 各平台正面率
    pos_rate = d_inc.groupby("source")["is_positive"].mean().sort_values(ascending=False)
    print("  各平台正面率：")
    for p, r in pos_rate.items():
        print(f"    {p:10s} {r*100:.1f}%")

    return res, res_bin, ct, included, excluded, n_other


def analyze_workform_sentiment(s, f):
    """Series vs Film × 情感 关联。只使用双方共有且覆盖充分的平台（n>=30 且 覆盖>=3）。
    否则平台构成不同会污染 form 比较（如 RT 只在 Film、MAL 主要在 Series）。"""
    sd = s[s["sentiment_final"] != "other"]
    fd = f[f["sentiment_final"] != "other"]
    s_elig, _ = eligible_platforms(sd)
    f_elig, _ = eligible_platforms(fd)
    common = sorted(set(s_elig) & set(f_elig))  # 共有且都准入的平台
    print(f"\n{'='*66}")
    print("[SERIES vs FILM] 情感分布差异（仅共有且覆盖充分的平台）")
    print(f"  Series 准入平台 {s_elig}；Film 准入平台 {f_elig}")
    print(f"  共有平台（用于正式比较）：{common}")
    print(f"{'='*66}")
    both = pd.concat([sd[sd["source"].isin(common)],
                      fd[fd["source"].isin(common)]], ignore_index=True)
    ct = pd.crosstab(both["work_form"], both["sentiment_final"])[SENT_ORDER]
    print(ct)
    res = run_chi2(ct)
    print(f"\n  χ²={res['chi2']:.2f}, df={res['dof']}, p={fmt_p(res['p'])}, V={res['cramers_v']:.3f}")
    print(f"  最小期望频数={res['min_expected']:.2f}"
          + ("  ⚠ 稀疏" if res["sparse_flag"] else "  ✓"))
    print(res["residuals"].round(2))
    return res, ct, common


def analyze_ne_zha_shared_title(f):
    """Ne Zha(2019) shared-title 稳健性分析：同一部作品，控制作品后看平台情感是否仍不同。
    用 Film 数据里 Ne Zha 在各平台的样本（RT/Reddit/X/YouTube 均>=30，MAL 仅 9 条单独列出）。"""
    print(f"\n{'='*66}")
    print("[Ne Zha shared-title] 同一部《哪吒》跨平台情感差异（控制作品）")
    print(f"{'='*66}")
    nz = f[(f["anime_name"] == "Ne Zha") & (f["sentiment_final"] != "other")].copy()
    # 平台准入：Ne Zha 单部作品内，平台样本 n>=30 才进正式检验
    nz_elig, nz_excl = [], []
    for src, g in nz.groupby("source"):
        (nz_elig if len(g) >= PLATFORM_MIN_N else nz_excl).append(src)
    print(f"  Ne Zha 各平台样本（排除 other 后）：")
    for src, g in nz.groupby("source"):
        print(f"    {src:10s} n={len(g):3d}")
    print(f"  进正式检验（n>=30）：{nz_elig}；仅展示：{nz_excl}")

    nz_inc = nz[nz["source"].isin(nz_elig)]
    ct = pd.crosstab(nz_inc["source"], nz_inc["sentiment_final"])[SENT_ORDER]
    print(ct)
    res = run_chi2(ct)
    print(f"\n  χ²={res['chi2']:.2f}, df={res['dof']}, p={fmt_p(res['p'])}, V={res['cramers_v']:.3f}")
    print(f"  最小期望频数={res['min_expected']:.2f}"
          + ("  ⚠ 稀疏" if res["sparse_flag"] else "  ✓"))
    print(res["residuals"].round(2))
    # 各平台正面率（同一部作品）
    nz_inc = nz_inc.copy()
    nz_inc["is_positive"] = (nz_inc["sentiment_final"] == "positive").astype(int)
    # 主口径：正面率二值检验（positive vs non-positive），避免 4 分类稀疏格
    ct_bin = pd.crosstab(nz_inc["source"], nz_inc["is_positive"])
    res_bin = run_chi2(ct_bin)
    print(f"\n  [主口径·正面率二值] χ²={res_bin['chi2']:.2f}, df={res_bin['dof']}, "
          f"p={fmt_p(res_bin['p'])}, V={res_bin['cramers_v']:.3f}")
    print(f"  最小期望频数={res_bin['min_expected']:.2f}"
          + ("  ⚠ 稀疏" if res_bin["sparse_flag"] else "  ✓"))
    pos_rate = nz_inc.groupby("source")["is_positive"].mean().sort_values(ascending=False)
    print("  各平台正面率（同一部《哪吒》）：")
    for p, r in pos_rate.items():
        print(f"    {p:10s} {r*100:.1f}%")
    return res, res_bin, ct, nz_elig


def analyze_topic_platform(df, work_form, included_platforms):
    """12 主题 × 平台（每个主题独立 0/1，2×k 卡方 + Bonferroni）。排除 other 作分母。"""
    d = df[(df["source"].isin(included_platforms)) & (df["sentiment_final"] != "other")].copy()
    print(f"\n{'='*66}")
    print(f"[{work_form.upper()}] 12 主题 × 平台 关联检验（Bonferroni α={ALPHA/12:.5f}，排除 other）")
    print(f"{'='*66}")

    rows = []
    alpha_bonf = ALPHA / len(TOPICS)
    for tid, zh in TOPICS:
        col = "topic_" + tid
        if d[col].sum() == 0:
            rows.append({"主题": zh, "命中数": 0, "χ²": np.nan, "p": np.nan,
                         "Bonf显著": False, "Cramér's V": np.nan, "结论": "无命中"})
            continue
        ct = pd.crosstab(d["source"], d[col])
        if ct.shape[0] < 2 or ct.shape[1] < 2:
            rows.append({"主题": zh, "命中数": int(d[col].sum()), "χ²": np.nan, "p": np.nan,
                         "Bonf显著": False, "Cramér's V": np.nan, "结论": "单平台或无变异"})
            continue
        res = run_chi2(ct)
        sig = res["p"] < alpha_bonf
        # 找该主题在哪些平台命中率最高/最低
        rate = d.groupby("source")[col].mean()
        hi = rate.idxmax(); lo = rate.idxmin()
        rows.append({
            "主题": zh, "命中数": int(d[col].sum()),
            "χ²": round(res["chi2"], 2), "p": res["p"],
            "Bonf显著": sig, "Cramér's V": round(res["cramers_v"], 3),
            "最高平台": f"{hi}({rate[hi]*100:.0f}%)", "最低平台": f"{lo}({rate[lo]*100:.0f}%)",
            "结论": "显著" if sig else "不显著",
        })

    res_df = pd.DataFrame(rows)
    print(res_df.to_string(index=False))
    return res_df


# ============ 绘图 ============
def plot_sentiment_stacked(ct, work_form):
    """平台 × 情感 堆叠百分比柱状图。"""
    pct = ct.div(ct.sum(axis=1), axis=0) * 100
    ax = pct.plot(kind="bar", stacked=True, figsize=(8, 5),
                  color=["#4caf50", "#9e9e9e", "#f44336", "#ff9800"])
    ax.set_ylabel("占比 %")
    ax.set_title(f"{work_form.upper()}：各平台情感分布（排除 other）")
    ax.legend(title="情感", bbox_to_anchor=(1.02, 1), loc="upper left")
    ax.set_ylim(0, 100)
    for c in ax.containers:
        ax.bar_label(c, fmt="%.0f%%", label_type="center", fontsize=7, color="white")
    plt.tight_layout()
    plt.savefig(f"07_platform_sentiment_{work_form}.png", dpi=110)
    plt.close()


def plot_residual_heatmap(res_df, work_form):
    """标准化残差热力图。"""
    fig, ax = plt.subplots(figsize=(7, 4))
    cmap = matplotlib.colormaps["RdBu_r"]
    vmax = np.nanmax(np.abs(res_df.values)) if res_df.size else 1
    im = ax.imshow(res_df.values, cmap=cmap, vmin=-vmax, vmax=vmax, aspect="auto")
    ax.set_xticks(range(len(res_df.columns))); ax.set_xticklabels(res_df.columns)
    ax.set_yticks(range(len(res_df.index))); ax.set_yticklabels(res_df.index)
    for i in range(res_df.shape[0]):
        for j in range(res_df.shape[1]):
            ax.text(j, i, f"{res_df.iloc[i, j]:.1f}", ha="center", va="center", fontsize=9)
    ax.set_title(f"{work_form.upper()}：平台×情感 标准化残差（红=偏多 蓝=偏少）")
    fig.colorbar(im, ax=ax, label="调整后标准化残差 z")
    plt.tight_layout()
    plt.savefig(f"07_residual_{work_form}.png", dpi=110)
    plt.close()


def plot_topic_platform_heatmap(df, included_platforms, work_form):
    """主题 × 平台 命中率热力图（排除 other 作分母）。"""
    d = df[(df["source"].isin(included_platforms)) & (df["sentiment_final"] != "other")]
    mat = pd.DataFrame(index=[zh for _, zh in TOPICS],
                       columns=sorted(included_platforms), dtype=float)
    for tid, zh in TOPICS:
        rate = d.groupby("source")["topic_" + tid].mean()
        for p in included_platforms:
            mat.loc[zh, p] = rate.get(p, np.nan) * 100
    fig, ax = plt.subplots(figsize=(8, 9))
    im = ax.imshow(mat.values.astype(float), cmap="YlOrRd", aspect="auto")
    ax.set_xticks(range(len(mat.columns))); ax.set_xticklabels(mat.columns)
    ax.set_yticks(range(len(mat.index))); ax.set_yticklabels(mat.index, fontsize=9)
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            v = mat.iloc[i, j]
            ax.text(j, i, f"{v:.0f}%" if not np.isnan(v) else "-", ha="center", va="center", fontsize=8)
    ax.set_title(f"{work_form.upper()}：各主题在各平台命中率（%）")
    fig.colorbar(im, ax=ax, label="命中率 %")
    plt.tight_layout()
    plt.savefig(f"07_topic_platform_{work_form}.png", dpi=110)
    plt.close()


# ============ 主流程 ============
def main():
    s, f = load_data()
    print(f"[读入] series {len(s)} 条, film {len(f)} 条")

    # 准备 Excel 写入
    out_xlsx = "07_association_results.xlsx"
    writer = pd.ExcelWriter(out_xlsx, engine="openpyxl")

    summary_rows = []  # 汇总所有检验结论，供写报告

    # ---- Series 平台 × 情感 ----
    res_s, res_bin_s, ct_s, inc_s, exc_s, other_s = analyze_sentiment_platform(s, "series", "Series")
    plot_sentiment_stacked(ct_s, "series")
    plot_residual_heatmap(res_s["residuals"], "series")
    ct_s.to_excel(writer, sheet_name="Series_平台×情感")
    res_s["residuals"].round(3).to_excel(writer, sheet_name="Series_标准化残差")
    summary_rows.append({
        "检验": "Series 平台×情感", "χ²": round(res_s["chi2"], 2),
        "df": res_s["dof"], "p": res_s["p"], "Cramér's V": round(res_s["cramers_v"], 3),
        "最小期望": round(res_s["min_expected"], 2), "稀疏警告": res_s["sparse_flag"],
        "纳入平台": ",".join(inc_s), "排除平台": ",".join(exc_s),
    })

    # ---- Film 平台 × 情感 ----
    res_f, res_bin_f, ct_f, inc_f, exc_f, other_f = analyze_sentiment_platform(f, "film", "Film")
    plot_sentiment_stacked(ct_f, "film")
    plot_residual_heatmap(res_f["residuals"], "film")
    ct_f.to_excel(writer, sheet_name="Film_平台×情感")
    res_f["residuals"].round(3).to_excel(writer, sheet_name="Film_标准化残差")
    summary_rows.append({
        "检验": "Film 平台×情感", "χ²": round(res_f["chi2"], 2),
        "df": res_f["dof"], "p": res_f["p"], "Cramér's V": round(res_f["cramers_v"], 3),
        "最小期望": round(res_f["min_expected"], 2), "稀疏警告": res_f["sparse_flag"],
        "纳入平台": ",".join(inc_f), "排除平台": ",".join(exc_f),
    })

    # ---- Series vs Film（仅共有且覆盖充分平台）----
    res_wf, ct_wf, common_wf = analyze_workform_sentiment(s, f)
    ct_wf.to_excel(writer, sheet_name="SeriesFilm_情感")
    summary_rows.append({
        "检验": "Series vs Film 情感（共有平台）", "χ²": round(res_wf["chi2"], 2),
        "df": res_wf["dof"], "p": res_wf["p"], "Cramér's V": round(res_wf["cramers_v"], 3),
        "最小期望": round(res_wf["min_expected"], 2), "稀疏警告": res_wf["sparse_flag"],
        "纳入平台": ",".join(common_wf), "排除平台": "非共有或低覆盖",
    })

    # ---- Ne Zha shared-title ----
    res_nz, res_bin_nz, ct_nz, nz_elig = analyze_ne_zha_shared_title(f)
    ct_nz.to_excel(writer, sheet_name="NeZha_shared_title")
    # 主口径：正面率二值（positive vs non-positive，格子充实、无稀疏）
    summary_rows.append({
        "检验": "Ne Zha shared-title（正面率二值）", "χ²": round(res_bin_nz["chi2"], 2),
        "df": res_bin_nz["dof"], "p": res_bin_nz["p"], "Cramér's V": round(res_bin_nz["cramers_v"], 3),
        "最小期望": round(res_bin_nz["min_expected"], 2), "稀疏警告": res_bin_nz["sparse_flag"],
        "纳入平台": ",".join(nz_elig), "排除平台": "Ne Zha 单平台 n<30",
    })
    # 辅助：四分类检验（存在稀疏格 min expected≈2.87，仅作参考）
    summary_rows.append({
        "检验": "Ne Zha shared-title（四分类）", "χ²": round(res_nz["chi2"], 2),
        "df": res_nz["dof"], "p": res_nz["p"], "Cramér's V": round(res_nz["cramers_v"], 3),
        "最小期望": round(res_nz["min_expected"], 2), "稀疏警告": res_nz["sparse_flag"],
        "纳入平台": ",".join(nz_elig), "排除平台": "Ne Zha 单平台 n<30",
    })

    # ---- 12 主题 × 平台 ----
    topic_s = analyze_topic_platform(s, "series", inc_s)
    topic_f = analyze_topic_platform(f, "film", inc_f)
    topic_s.to_excel(writer, sheet_name="Series_主题×平台", index=False)
    topic_f.to_excel(writer, sheet_name="Film_主题×平台", index=False)
    plot_topic_platform_heatmap(s, inc_s, "series")
    plot_topic_platform_heatmap(f, inc_f, "film")

    # ---- 汇总 sheet ----
    pd.DataFrame(summary_rows).to_excel(writer, sheet_name="检验汇总", index=False)

    # ---- 说明 sheet ----
    notes = pd.DataFrame({"说明": [
        "1. 情感统计排除 other（无关/引战），other 单独审计，不进入分母。",
        "2. 平台准入：n>=30 且 覆盖作品数>=3 才进入卡方检验（与 04 三口径一致）。",
        "3. 稀疏表处理：打印最小期望频数；若期望<5 的格子>20%，标 warning 并提示 p 值仅供参考。",
        "4. 稳健性：另跑正面率（positive vs 非positive）2×k 检验，正面率~65%格子充实更稳。",
        "5. 主题多标签：12 主题各自 0/1 独立检验 + Bonferroni 校正（α=0.05/12≈0.00417），不做 explode；且排除 other 作分母。",
        "6. Cramér's V：<0.1 弱 / 0.1-0.3 中 / >0.5 强。",
        "7. 标准化残差：|z|>1.96 显著，|z|>2.58 很强；正=该格偏多，负=偏少。",
        f"8. Series 准入平台：{inc_s}；Film 准入平台：{inc_f}。",
        "9. Series vs Film 只比共有且覆盖充分平台（YouTube+X）。",
        "10. Ne Zha shared-title：主口径=正面率二值检验（positive vs non-positive，避免 4 分类稀疏格）；四分类检验仅作辅助参考。",
        "11. Film 的 Reddit 仅覆盖《哪吒》1 部作品，不进入 Film 正式平台推断，只在 shared-title 里用。",
    ]})
    notes.to_excel(writer, sheet_name="说明", index=False)

    writer.close()
    print(f"\n[输出] {out_xlsx} 已生成，含检验汇总/交叉表/标准化残差/主题×平台/NeZha shared-title/说明 等 sheet")
    print("[输出] 6 张 PNG 热力图已生成")


if __name__ == "__main__":
    main()
