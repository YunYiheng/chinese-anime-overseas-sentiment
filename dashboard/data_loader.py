# -*- coding: utf-8 -*-
"""
data_loader.py —— 数据加载层（只读，不做统计）。

唯一职责：把「封版后」的最终数据文件读成 pandas DataFrame / dict。
任何统计口径（platform_balanced、χ²、残差等）都来自这些文件本身，
看板自己绝不重算一套，避免和报告对不上。

文件位置：dashboard/ 的上一级是项目根目录，数据都在根目录与 storage2/ 下。
"""
from pathlib import Path

import pandas as pd

# 项目根目录 = 本文件上级的上级（dashboard/ -> 根目录）
ROOT = Path(__file__).resolve().parent.parent

ALL_CSV = ROOT / "analytical_all.csv"
SERIES_CSV = ROOT / "analytical_series.csv"
FILM_CSV = ROOT / "analytical_film.csv"
SERIES_SENT_XLSX = ROOT / "storage2" / "series_pipeline" / "series_sentiment_final_summary.xlsx"
FILM_SENT_XLSX = ROOT / "storage2" / "film_pipeline" / "film_sentiment_final_summary.xlsx"
ASSOC_XLSX = ROOT / "07_association_results.xlsx"

_cache = {}


def _load(key, loader):
    """简单缓存：同一文件只读一次。"""
    if key not in _cache:
        _cache[key] = loader()
    return _cache[key]


def all():
    return _load("all", lambda: pd.read_csv(ALL_CSV, encoding="utf-8-sig"))


def series():
    return _load("series", lambda: pd.read_csv(SERIES_CSV, encoding="utf-8-sig"))


def film():
    return _load("film", lambda: pd.read_csv(FILM_CSV, encoding="utf-8-sig"))


def sentiment_koujing(form):
    """读取封版的「三口径对比」sheet，返回 {'platform_balanced': {...}, 'pooled': {...}}。

    注意：series 用「4 平台等权」、film 用「3 平台等权」，列名不同，
    所以用前缀 startswith 匹配，而不是写死列名。
    """
    path = SERIES_SENT_XLSX if form == "series" else FILM_SENT_XLSX
    df = pd.read_excel(path, sheet_name="三口径对比", header=1)
    df.columns = [str(c).strip() for c in df.columns]
    df = df[df["情感"].notna()].copy()

    out = {}
    for prefix, key in (("platform_balanced", "platform_balanced"), ("pooled", "pooled")):
        col = [c for c in df.columns if c.startswith(prefix)][0]
        out[key] = {str(r["情感"]).strip(): float(r[col]) for _, r in df.iterrows()}
    return out


def assoc(sheet):
    """读取 07_association_results.xlsx 的指定 sheet（关联分析封版结果）。

    sheet 例：'Series_平台×情感' / 'Series_标准化残差' / 'NeZha_shared_title' 等。
    """
    return _load(f"assoc:{sheet}", lambda: pd.read_excel(ASSOC_XLSX, sheet_name=sheet))
