# -*- coding: utf-8 -*-
"""
06 数据封版 —— 产出最终三张分析表（给关联分析 + Flask 看板 + 最终报告用）

输入（05 主题分析已跑完的两份标签表，内含 情感+主题 全部字段）：
  storage2/series_pipeline/series_topic_labeled.csv   (1233 条)
  storage2/film_pipeline/film_topic_labeled.csv       (1125 条)

输出（根目录，三张"冻结"的分析表）：
  analytical_series.csv   —— 6 部剧集 × 5 平台
  analytical_film.csv     —— 7 部电影 × 4 平台
  analytical_all.csv      —— series + film 合并

本脚本做三件事（对应 GPT方案.docx 数据封版要求）：
  1. score 统一成 float（可缺失 NaN）。Series 原为 int，转 float 不丢精度
     （MAL 1-10 / Reddit karma / YouTube·X 点赞 / AniList 0-100 / RT 0.5-5 星，
      各平台原始量表不同，不能跨平台直接比大小）。
  2. 新增 global_record_id 解决 record_id 撞号：
       Series -> SREC00001...  Film -> FREC00001...
     （原来 series 和 film 都用 REC00001... 会撞号，这里全局重编号。）
  3. 字段精简对齐，统一 work_form / language / sentiment_final / topic 命名。

字段说明（19 列）：
  global_record_id  全局唯一编号（SREC/FREC 前缀）
  record_id         原管线内编号（保留溯源）
  anime_name        作品名（规范英文名）
  work_form         series / film
  source            平台（Reddit/YouTube/X/AniList/MAL/RT）
  comment_id        平台内评论 ID（用于去重/溯源）
  author            作者名
  post_time         发布时间
  language          lang_detected（ISO 码：en/zh/es/id/ja/...，unknown=识别不出，mixed=中英混）
  lang_group        语言分组（低频语言已合并为"其他语言"）
  score             原始互动量/评分（float，跨平台不可比）
  content           清洗后正文（content_clean）
  sentiment_pred    模型预测情感
  manual_sentiment  人工复核情感（未复核为 NaN）
  sentiment_final   最终情感（manual 非空取 manual，否则取 pred）
  topic             命中的主题列表（中文，全角分号分隔）
  topic_count       命中主题数
  topic_matched_keywords  命中词（带语言前缀，用于 QA/审计）
  page_url          原始链接
"""
import sys
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SERIES_IN = "storage2/series_pipeline/series_topic_labeled.csv"
FILM_IN = "storage2/film_pipeline/film_topic_labeled.csv"

# 最终分析表的字段（顺序即输出列顺序）
OUT_COLUMNS = [
    "global_record_id", "record_id", "anime_name", "work_form", "source",
    "comment_id", "author", "post_time", "language", "lang_group",
    "score", "content", "sentiment_pred", "manual_sentiment", "sentiment_final",
    "topic", "topic_count", "topic_matched_keywords", "page_url",
]


def build(df, prefix, work_form):
    """把 topic_labeled 表加工成 analytical 表。prefix=SREC/FREC。"""
    out = pd.DataFrame()

    # -- 全局唯一编号：前缀 + 5 位序号（按原 record_id 顺序稳定编号） --
    out["global_record_id"] = [
        f"{prefix}{i:05d}" for i in range(1, len(df) + 1)
    ]

    # -- 直接搬运 / 改名 --
    out["record_id"] = df["record_id"]
    out["anime_name"] = df["anime_name"]
    out["work_form"] = work_form
    out["source"] = df["source"]
    out["comment_id"] = df["comment_id"]
    out["author"] = df["author"]
    out["post_time"] = df["post_time"]
    out["language"] = df["lang_detected"]
    out["lang_group"] = df["lang_group"]

    # -- score 统一 float（可缺失）。Series 整数 -> float 无损 --
    out["score"] = pd.to_numeric(df["score"], errors="coerce").astype("float64")

    # -- 正文用清洗后文本（分析就用的这份） --
    out["content"] = df["content_clean"]

    # -- 情感三列 --
    out["sentiment_pred"] = df["sentiment_pred"]
    out["manual_sentiment"] = df["manual_sentiment"]
    out["sentiment_final"] = df["sentiment_final"]

    # -- 主题 --
    out["topic"] = df["topic_list"].fillna("")
    out["topic_count"] = pd.to_numeric(df["topic_count"], errors="coerce").fillna(0).astype("int64")
    out["topic_matched_keywords"] = df["topic_matched_keywords"].fillna("")

    out["page_url"] = df["page_url"]

    return out[OUT_COLUMNS]


def main():
    # -- 读两份标签表 --
    series = pd.read_csv(SERIES_IN, encoding="utf-8-sig")
    film = pd.read_csv(FILM_IN, encoding="utf-8-sig")
    print(f"[读入] series {len(series)} 条, film {len(film)} 条")

    # -- 校验 form 列，确保没拿错文件 --
    assert set(series["form"].unique()) == {"series"}, f"series 文件 form 异常: {series['form'].unique()}"
    assert set(film["form"].unique()) == {"film"}, f"film 文件 form 异常: {film['form'].unique()}"

    # -- 加工成三张表 --
    aseries = build(series, "SREC", "series")
    afilm = build(film, "FREC", "film")
    aall = pd.concat([aseries, afilm], ignore_index=True)

    # -- 全局编号唯一性校验 --
    assert aall["global_record_id"].is_unique, "global_record_id 出现重复！"

    # -- 写出（utf-8-sig 让 Excel 不乱码） --
    aseries.to_csv("analytical_series.csv", index=False, encoding="utf-8-sig")
    afilm.to_csv("analytical_film.csv", index=False, encoding="utf-8-sig")
    aall.to_csv("analytical_all.csv", index=False, encoding="utf-8-sig")

    print(f"\n[封版完成]")
    print(f"  analytical_series.csv  {len(aseries)} 条")
    print(f"  analytical_film.csv    {len(afilm)} 条")
    print(f"  analytical_all.csv     {len(aall)} 条")
    print(f"\n[score 类型] series={aseries['score'].dtype}, film={afilm['score'].dtype}")
    print(f"[global_record_id 样例] {aall['global_record_id'].iloc[0]} / {aall['global_record_id'].iloc[len(aseries)]}")
    print(f"[work_form 分布]\n{aall['work_form'].value_counts().to_string()}")
    print(f"[source 分布]\n{aall['source'].value_counts().to_string()}")
    print(f"[sentiment_final 分布]\n{aall['sentiment_final'].value_counts().to_string()}")


if __name__ == "__main__":
    main()
