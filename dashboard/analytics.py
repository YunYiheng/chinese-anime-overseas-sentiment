# -*- coding: utf-8 -*-
"""
analytics.py —— 分析层：把数据组织成 Dashboard 前端需要的 JSON。

原则：只复用 data_loader 读到的封版数据，不在这里重写统计口径。
"""
from collections import Counter

import pandas as pd

try:
    import data_loader as dl  # 本地：python app.py
except ImportError:
    import dashboard.data_loader as dl  # 云部署：gunicorn dashboard.app:app

# 情感展示顺序（与报告三口径图一致：正面/中性/混合/负面）
SENT_ORDER = ["positive", "neutral", "mixed", "negative"]

# 准入平台（与报告 / 04 / 07 脚本完全一致）
ADMITTED = {
    "series": {"MAL", "Reddit", "X", "YouTube"},
    "film": {"RT", "X", "YouTube"},
}


def get_kpis():
    """首页 6 个 KPI，全部从 analytical_all.csv 现算（不含 other 的才是主样本）。"""
    a = dl.all()
    series_main = int(((a["work_form"] == "series") & (a["sentiment_final"] != "other")).sum())
    film_main = int(((a["work_form"] == "film") & (a["sentiment_final"] != "other")).sum())
    return {
        "total": int(len(a)),                        # 总采集量（含 other 89 条）
        "series_main": series_main,                  # Series 主样本（排除 other）
        "film_main": film_main,                      # Film 主样本（排除 other）
        "n_platforms": int(a["source"].nunique()),   # 平台数
        "n_series_works": int(a[a["work_form"] == "series"]["anime_name"].nunique()),
        "n_film_works": int(a[a["work_form"] == "film"]["anime_name"].nunique()),
    }


def get_platform_dist():
    """两层各平台样本量（排除 other），按样本量降序，附带是否准入标记。"""
    a = dl.all()
    out = {}
    for form in ("series", "film"):
        sub = a[(a["work_form"] == form) & (a["sentiment_final"] != "other")]
        vc = sub["source"].value_counts()
        out[form] = [
            {"platform": p, "count": int(vc[p]), "admitted": p in ADMITTED[form]}
            for p in vc.index
        ]
    return out


def get_sentiment():
    """两层情感分布（platform_balanced 主口径 + pooled 附注），直接读封版 xlsx。"""
    return {form: dl.sentiment_koujing(form) for form in ("series", "film")}


# ------------------------------------------------------------------ 通用（Series/Film）页
# 07 结果 sheet 前缀：series -> "Series_平台×情感" 等
FORM_SHEET = {"series": "Series", "film": "Film"}


def _df_for(form):
    return dl.series() if form == "series" else dl.film()


def get_options(form):
    """筛选器可选项：作品 / 平台 / 情感（情感只给 4 个主情感，other 不进统计）。"""
    s = _df_for(form)
    return {
        "works": sorted(s["anime_name"].unique().tolist()),
        "platforms": sorted(s["source"].unique().tolist()),
        "sentiments": SENT_ORDER,
    }


def _filter(form, work=None, platform=None, sentiment=None):
    """主样本（排除 other）按条件过滤。"""
    s = _df_for(form)
    s = s[s["sentiment_final"] != "other"]
    if work:
        s = s[s["anime_name"] == work]
    if platform:
        s = s[s["source"] == platform]
    if sentiment:
        s = s[s["sentiment_final"] == sentiment]
    return s


def get_data(form, work=None, platform=None, sentiment=None):
    """当前筛选下的：平台样本量 / 情感分布 / 主题命中 Top（主题多标签，按「；」拆分）。"""
    s = _filter(form, work, platform, sentiment)
    total = len(s)

    platform_dist = [
        {"platform": p, "count": int(c), "admitted": p in ADMITTED[form]}
        for p, c in s["source"].value_counts().items()
    ]

    vc = s["sentiment_final"].value_counts()
    sentiment_dist = [
        {
            "sentiment": k,
            "count": int(vc.get(k, 0)),
            "pct": round(vc.get(k, 0) / total * 100, 1) if total else 0.0,
        }
        for k in SENT_ORDER
    ]

    counter = Counter()
    for v in s["topic"].dropna():
        for t in str(v).split("；"):
            t = t.strip()
            if t:
                counter[t] += 1
    topic_top = [{"topic": t, "count": c} for t, c in counter.most_common()]

    return {
        "total": total,
        "platform_dist": platform_dist,
        "sentiment_dist": sentiment_dist,
        "topic_top": topic_top,
    }


def _df_to_rows(df):
    """把「source × positive/neutral/negative/mixed」封版表转成 [{platform, ...}]。"""
    rows = []
    for _, r in df.iterrows():
        row = {"platform": str(r["source"])}
        for c in ["positive", "neutral", "negative", "mixed"]:
            row[c] = float(r[c])
        rows.append(row)
    return rows


def get_association(form):
    """平台 × 情感交叉表 + 标准化残差（直接读 07 封版结果，不重算）。"""
    sheet = FORM_SHEET[form]
    return {
        "platform_sentiment": _df_to_rows(dl.assoc(f"{sheet}_平台×情感")),
        "residual": _df_to_rows(dl.assoc(f"{sheet}_标准化残差")),
    }


def get_balanced(form):
    """情感主口径 platform_balanced（封版，与 pooled 联动图区分）。"""
    return get_sentiment()[form]["platform_balanced"]


# ------------------------------------------------------------------ 评论浏览器
def get_comments(form, work=None, platform=None, sentiment=None, offset=0, limit=20):
    """评论浏览器：主样本（排除 other，除非显式指定 other）+ 筛选 + 分页。"""
    df = dl.series() if form == "series" else dl.film()
    if sentiment:
        df = df[df["sentiment_final"] == sentiment]
    else:
        df = df[df["sentiment_final"] != "other"]
    if work:
        df = df[df["anime_name"] == work]
    if platform:
        df = df[df["source"] == platform]

    total = len(df)
    rows = []
    for _, r in df.iloc[offset:offset + limit].iterrows():
        score = r["score"]
        rows.append({
            "record_id": str(r["global_record_id"]),
            "work": str(r["anime_name"]),
            "platform": str(r["source"]),
            "sentiment": str(r["sentiment_final"]),
            "score": None if pd.isna(score) else float(score),
            "time": str(r["post_time"]) if pd.notna(r["post_time"]) else "",
            "content": str(r["content"]) if pd.notna(r["content"]) else "",
        })
    return {"total": int(total), "rows": rows}


# ------------------------------------------------------------------ 关联分析页（读 07 封版，不重算）
def _summary_row(df, name):
    """从「检验汇总」sheet 取一行检验结论，转成前端友好的 dict。"""
    r = df[df["检验"] == name].iloc[0]
    return {
        "chi2": float(r["χ²"]),
        "df": int(r["df"]),
        "p": float(r["p"]),
        "v": float(r["Cramér's V"]),
        "min_expected": float(r["最小期望"]),
        "sparse": bool(r["稀疏警告"]),
        "included": str(r["纳入平台"]),
        "excluded": str(r["排除平台"]),
    }


def _topic_rows(sheet):
    """把「主题×平台」封版表转成 [{topic, hits, chi2, p, significant, v, hi, lo}]。"""
    rows = []
    for _, r in dl.assoc(sheet).iterrows():
        rows.append({
            "topic": str(r["主题"]),
            "hits": int(r["命中数"]),
            "chi2": float(r["χ²"]),
            "p": float(r["p"]),
            "significant": bool(r["Bonf显著"]),
            "v": float(r["Cramér's V"]),
            "hi": str(r["最高平台"]),
            "lo": str(r["最低平台"]),
        })
    return rows


def get_association_page():
    """Association 页全部数据：检验汇总 KPI + 残差热力图 + Ne Zha 正面率 + 主题表。"""
    summary = dl.assoc("检验汇总")

    nz = dl.assoc("NeZha_shared_title")
    rates = []
    for _, r in nz.iterrows():
        pos = int(r["positive"])
        total = pos + int(r["neutral"]) + int(r["negative"]) + int(r["mixed"])
        rates.append({
            "platform": str(r["source"]),
            "positive": pos,
            "total": total,
            "rate": round(pos / total * 100, 1) if total else 0.0,
        })
    rates.sort(key=lambda d: -d["rate"])

    return {
        "platform_sentiment": {
            "series": _summary_row(summary, "Series 平台×情感"),
            "film": _summary_row(summary, "Film 平台×情感"),
        },
        "series_vs_film": _summary_row(summary, "Series vs Film 情感（共有平台）"),
        "nezha": _summary_row(summary, "Ne Zha shared-title（正面率二值）"),
        "nezha_fourclass": _summary_row(summary, "Ne Zha shared-title（四分类）"),
        "residual": {
            "series": _df_to_rows(dl.assoc("Series_标准化残差")),
            "film": _df_to_rows(dl.assoc("Film_标准化残差")),
        },
        "nezha_rates": rates,
        "topics": {
            "series": _topic_rows("Series_主题×平台"),
            "film": _topic_rows("Film_主题×平台"),
        },
    }
