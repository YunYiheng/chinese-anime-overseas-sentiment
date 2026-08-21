# -*- coding: utf-8 -*-
"""
00_split_series.py
==================
Series 层输入准备：从「合并后的全量 03」里按 form 拆出 series 部分，
并把人工复核表里混入的电影(Ne Zha)记录过滤掉，生成 Series 层独立输入。

为什么这么做：
    Phase 2 决定把数据集拆成 Series(剧集) / Film(电影) 两条独立管线，
    因为「作品形式」是隐藏变量（剧集观众 vs 电影观众评价习惯不同）。
    根目录的 03_sentiment_all.csv 是合并后的全量（series 1233 + film 235），
    复核表 series_sentiment_review_core.xlsx 里也混进了 65 条 Ne Zha(film)。

筛选口径（不写死"65 条 Ne Zha"，按稳健规则）：
    1. 主规则：form == "series"（数据里已打好 series/film 标识）
    2. 交叉校验：anime_name 必须落在 Series 作品名单（6 部剧集）里
       若出现 form 与作品名单矛盾，打印告警供人工核对（正常应为 0 条）

输入（只读，不动）：
    ../../03_sentiment_all.csv                根目录合并全量（1468 条）
    ../../series_sentiment_review_core.xlsx   根目录复核表（349 条，含 65 条 film）

输出（写入本目录 storage2/series_pipeline/）：
    03_sentiment_all.csv               series 全量（1233 条，6 部剧集 × 5 平台）
    series_sentiment_review_core.xlsx  series 复核表（284 条，已剔除电影）

用法：python 00_split_series.py
"""

import os
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

# 脚本所在目录 = storage2/series_pipeline/，根目录在往上两级
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

INPUT_CSV = os.path.join(ROOT, "03_sentiment_all.csv")
INPUT_XLSX = os.path.join(ROOT, "series_sentiment_review_core.xlsx")

OUT_CSV = os.path.join(HERE, "03_sentiment_all.csv")
OUT_XLSX = os.path.join(HERE, "series_sentiment_review_core.xlsx")

# Series 作品名单（6 部剧集）——用于与 form 列做交叉校验
SERIES_WORKS = ["Link Click", "RMJI", "Ling Cage", "Soul Land", "BTTH", "Scissor Seven"]
# Film 作品名单（7 部电影）——仅用于告警提示，不参与 series 筛选
FILM_WORKS = ["Ne Zha", "Ne Zha 2", "White Snake", "Jiang Ziya",
              "New Gods: Nezha Reborn", "New Gods: Yang Jian", "I Am What I Am"]

SHEET_CORE = "核心复核清单"
SHEET_EXTRA = "补充抽审清单"


def main():
    # ---------- 1. 拆全量 03：form == series ----------
    df = pd.read_csv(INPUT_CSV, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    print(f"[1/3] 读取合并全量 {os.path.basename(INPUT_CSV)}: {len(df)} 条")
    print(f"      form 分布: {dict(df['form'].value_counts())}")

    series = df[df["form"] == "series"].copy()
    print(f"      form==series 共 {len(series)} 条")

    # 交叉校验：series 里不应出现电影作品名
    film_in_series = series[series["anime_name"].isin(FILM_WORKS)]
    if len(film_in_series):
        print(f"      ⚠ 告警: series 数据里有 {len(film_in_series)} 条电影作品名，请人工核对:")
        print(film_in_series["anime_name"].value_counts().to_string())
    else:
        print("      ✓ series 数据里无电影作品名（form 与作品名单一致）")

    series.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    print(f"      已写入 {os.path.basename(OUT_CSV)}")

    # ---------- 2. 过滤复核表：form == series ----------
    xl = pd.ExcelFile(INPUT_XLSX)
    core = xl.parse(SHEET_CORE, dtype=str, keep_default_na=False)
    extra = xl.parse(SHEET_EXTRA, dtype=str, keep_default_na=False)
    print(f"\n[2/3] 读取复核表 {os.path.basename(INPUT_XLSX)}:")
    print(f"      核心复核清单 {len(core)} 条, 补充抽审清单 {len(extra)} 条")

    for name, tab in [("核心", core), ("补充", extra)]:
        print(f"      {name}表单 form 分布: {dict(tab['form'].value_counts())}")

    # 主规则 form==series + 交叉校验作品名单
    core_s = core[core["form"] == "series"].copy()
    extra_s = extra[extra["form"] == "series"].copy()
    removed_core = len(core) - len(core_s)
    removed_extra = len(extra) - len(extra_s)
    print(f"      过滤后: 核心 {len(core_s)} 条(剔除 {removed_core} 条电影), "
          f"补充 {len(extra_s)} 条(剔除 {removed_extra} 条电影)")

    # 交叉校验：留下的 series 记录，作品名必须都在 6 部剧集名单里
    for name, tab in [("核心", core_s), ("补充", extra_s)]:
        bad = tab[~tab["anime_name"].isin(SERIES_WORKS)]
        if len(bad):
            print(f"      ⚠ 告警: {name}表单里有 {len(bad)} 条 form==series 但作品名不在剧集名单:")
            print(bad[["record_id", "anime_name", "form"]].to_string())
        else:
            print(f"      ✓ {name}表单作品名全部在 Series 名单内")
    print(f"      过滤后合计 {len(core_s) + len(extra_s)} 条, manual_sentiment 空白 "
          f"{int((core_s['manual_sentiment']=='') .sum()) + int((extra_s['manual_sentiment']=='') .sum())} 条")

    # ---------- 3. 重建 5-sheet 复核表（只更新两张数据表 + 重算覆盖/统计） ----------
    print(f"\n[3/3] 重建 series 复核表 -> {os.path.basename(OUT_XLSX)}")
    all_s = pd.concat([core_s, extra_s], ignore_index=True)

    with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as writer:
        # 操作说明
        notes = [
            "Series 层人工复核清单（已按 form==series 过滤掉电影/Ne Zha 记录）",
            "",
            "本文件由 00_split_series.py 生成：",
            "  - 数据源：根目录合并全量 03_sentiment_all.csv（form 列）",
            "  - 复核源：根目录 series_sentiment_review_core.xlsx",
            "  - 主规则：form == 'series'",
            "  - 交叉校验：anime_name 必须属于 6 部剧集（Link Click/RMJI/Ling Cage/Soul Land/BTTH/Scissor Seven）",
            "",
            "manual_sentiment / manual_note 为人工已填结果，只读；",
            "后续由 04_finalize_sentiment.py 回填生成 sentiment_final。",
        ]
        pd.DataFrame({"说明": notes}).to_excel(writer, sheet_name="操作说明", index=False)

        # 两张数据表（保持原列顺序，只需 record_id/anime_name/form/.../manual 列都在）
        core_s.to_excel(writer, sheet_name=SHEET_CORE, index=False)
        extra_s.to_excel(writer, sheet_name=SHEET_EXTRA, index=False)

        # 规则统计（简版：按 queue_group 计数 + 总量）
        stat_rows = [
            ["过滤后核心复核清单(必审)条数", len(core_s)],
            ["过滤后补充抽审清单(抽样)条数", len(extra_s)],
            ["过滤后复核总量", len(all_s)],
            ["剔除的电影(Ne Zha)记录数", removed_core + removed_extra],
            ["manual_sentiment 已填条数", int((all_s["manual_sentiment"] != "").sum())],
            ["manual_sentiment 空白条数", int((all_s["manual_sentiment"] == "").sum())],
        ]
        stat_df = pd.DataFrame(stat_rows, columns=["统计项", "数量"])
        stat_df.to_excel(writer, sheet_name="规则统计", index=False)

        # 平台×作品覆盖情况
        cov = all_s.groupby(["source", "anime_name"]).size().rename("复核数")
        must_c = core_s.groupby(["source", "anime_name"]).size().rename("必审")
        sup_c = extra_s.groupby(["source", "anime_name"]).size().rename("抽样")
        cov_tbl = pd.DataFrame(cov).join(pd.DataFrame(must_c)).join(pd.DataFrame(sup_c))
        cov_tbl = cov_tbl.fillna(0).astype({"复核数": int, "必审": int, "抽样": int})
        cov_tbl = cov_tbl.sort_index().reset_index()
        cov_tbl.to_excel(writer, sheet_name="平台×作品覆盖情况", index=False)

    print(f"      已写入 {os.path.basename(OUT_XLSX)}")
    print(f"\n完成。Series 输入就绪: 03={len(series)} 条, 复核={len(all_s)} 条")


if __name__ == "__main__":
    main()
