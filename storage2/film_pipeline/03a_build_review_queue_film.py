# -*- coding: utf-8 -*-
"""
03a_build_review_queue_film.py
===============================
Film 层：基于情感预测结果重建「风险导向人工复核清单」（不重跑情感模型）。

输入 : 03_sentiment_all.csv（03_sentiment_baseline.py 的输出）
输出 : sentiment_review_core.xlsx

复核规则（Film 版，在 Series 版基础上新增 RT 原生评分一致性检查）：
  一、必审（全平台，真高风险样本）：
      1. sentiment_pred == negative        （负面样本，研究核心）
      2. content_length < 10               （极端短文本，多为噪音/纯表情漏网）
      3. RT 原生 score 与模型预测矛盾      （新增，见下）
  二、分层抽审（其余高风险样本，按平台形式加权抽样，不全部审）：
      - 候选池 = 低置信(<0.65) ∪ 类间差(<0.20，标签冲突) ∪ 混合情感 ∪ 超长(>=1000字)
      - 抽样率按平台形式分档（长评平台少抽、短文本平台多抽）：
          MAL / AniList（长篇影评）: 8%
          Reddit / X / YouTube / RT（短文本）: 20%
      - 分层粒度 = 平台 × 作品 × 情感，每层至少 1 条 → 保证覆盖，不偏重大平台
  三、总量控制：目标 330~380，超上限按 score 从高到低裁掉抽审样本（保高互动/高评分）。

RT 评分一致性必审规则（利用 RT 原生观众评分 0.5~5 半星做交叉校验）：
  - score >= 4.0 且模型判 negative → 高分却负面，矛盾，必审
  - score <= 2.0 且模型判 positive → 低分却正面，矛盾，必审
  其余 RT 记录（2.5~3.5 中间分，或评分与情感一致）不额外必审，走常规抽样。

人工只填写 manual_sentiment / manual_note。
sentiment_final 不在本清单中，由后续脚本根据人工复核结果自动生成。

用法 : python 03a_build_review_queue_film.py
"""

import sys
import random

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.worksheet.datavalidation import DataValidation

# ============================== 配置区 ==============================
INPUT_CSV = "03_sentiment_all.csv"
OUT_XLSX = "sentiment_review_core.xlsx"

# 必审规则阈值
VERY_SHORT_CHARS = 10           # 极端短文本判定（<10 字视为噪音/纯表情）
RT_HIGH_SCORE = 4.0             # RT 高分阈值（>=4.0 星却判 negative → 必审）
RT_LOW_SCORE = 2.0              # RT 低分阈值（<=2.0 星却判 positive → 必审）

# 抽样候选池阈值（与 03_sentiment_baseline.py 口径一致）
CONF_THRESHOLD = 0.65
CLOSE_CALL = 0.20
VERY_LONG_CHARS = 1000

# 抽样率：按平台形式分档（长评平台少抽、短文本平台多抽）
LONG_FORM_PLATFORMS = {"MAL", "AniList"}
RATE_LONG = 0.08
RATE_SHORT = 0.20
STRAT_SEED = 42

# 总量目标（Film 负面样本(150)少于 Series(~329)，风险导向自然产出 ~229；
#  下限调至 200 以匹配 Film 实际负面规模，上限 380 保留作为总量封顶）
TARGET_MIN = 200
TARGET_MAX = 380

# 复核清单上下文列（供人工查看，只读）
CONTEXT_COLS = ["record_id", "anime_name", "form", "source", "author", "post_time", "score",
                "lang_group", "content_length", "content_clean",
                "sentiment_pred", "sentiment_score", "prob_positive",
                "prob_neutral", "prob_negative", "mixed_candidate"]


def describe_rule(i, is_neg, is_very_short, is_rt_conflict,
                  is_low, is_close, is_mixed, is_long):
    """返回命中的规则描述（必审或抽样）。"""
    parts = []
    if is_neg[i]:
        parts.append("负面")
    if is_very_short[i]:
        parts.append("极端短文本")
    if is_rt_conflict[i]:
        parts.append("RT评分冲突")
    if is_low[i]:
        parts.append("低置信")
    if is_close[i]:
        parts.append("类间差/标签冲突")
    if is_mixed[i]:
        parts.append("混合情感")
    if is_long[i]:
        parts.append("超长")
    return "; ".join(parts)


def main():
    print("=" * 60)
    print("Film 层：重建风险导向人工复核清单（不重跑情感模型）")
    print("=" * 60)

    # ---------- 1. 读入 ----------
    df = pd.read_csv(INPUT_CSV, encoding="utf-8-sig")
    print(f"读取 {INPUT_CSV}: {len(df)} 条")

    # ---------- 2. 派生布尔列 ----------
    probs = df[["prob_positive", "prob_neutral", "prob_negative"]].values
    max_prob = probs.max(axis=1)
    sorted_probs = np.sort(probs, axis=1)
    prob_diff = sorted_probs[:, -1] - sorted_probs[:, -2]
    is_low = max_prob < CONF_THRESHOLD
    is_close = prob_diff < CLOSE_CALL

    is_neg = (df["sentiment_pred"] == "negative").values
    is_very_short = (df["content_length"] < VERY_SHORT_CHARS).values
    is_mixed = (df["mixed_candidate"] == 1).values
    is_long = (df["content_length"] >= VERY_LONG_CHARS).values

    # RT 原生评分一致性冲突（新增必审）
    score_num = pd.to_numeric(df["score"], errors="coerce")
    is_rt = (df["source"] == "RT").values
    is_rt_high_neg = is_rt & (score_num >= RT_HIGH_SCORE).values & is_neg
    is_rt_low_pos = is_rt & (score_num <= RT_LOW_SCORE).values & (df["sentiment_pred"] == "positive").values
    is_rt_conflict = is_rt_high_neg | is_rt_low_pos

    # ---------- 3. 必审（负面 ∪ 极端短文本 ∪ RT评分冲突） ----------
    is_must = is_neg | is_very_short | is_rt_conflict
    n_must = int(is_must.sum())
    print(f"\n必审: {n_must} 条")
    print(f"  负面 {int(is_neg.sum())} ∪ 极端短文本 {int(is_very_short.sum())} ∪ RT评分冲突 {int(is_rt_conflict.sum())}")
    print(f"  RT评分冲突明细: 高星(>=4.0)却负面 {int(is_rt_high_neg.sum())} 条 / 低星(<=2.0)却正面 {int(is_rt_low_pos.sum())} 条")

    # ---------- 4. 抽样候选池（低置信 ∪ 类间差 ∪ 混合 ∪ 超长，且非必审） ----------
    pool_mask = (is_low | is_close | is_mixed | is_long) & ~is_must
    n_pool = int(pool_mask.sum())
    print(f"抽样候选池: {n_pool} 条 (低置信 {int((is_low & ~is_must).sum())} / "
          f"类间差 {int((is_close & ~is_must).sum())} / 混合 {int((is_mixed & ~is_must).sum())} / "
          f"超长 {int((is_long & ~is_must).sum())})")

    # ---------- 5. 分层抽样：平台 × 作品 × 情感，每层至少 1 条 ----------
    pool = df[pool_mask]
    rng = random.Random(STRAT_SEED)
    picked = set()
    cell_stat = {"long": 0, "short": 0}
    for (src, anime, pred), g in pool.groupby(["source", "anime_name", "sentiment_pred"]):
        rate = RATE_LONG if src in LONG_FORM_PLATFORMS else RATE_SHORT
        bucket = "long" if src in LONG_FORM_PLATFORMS else "short"
        cell_stat[bucket] += 1
        n = max(1, int(round(len(g) * rate)))
        for i in rng.sample(list(g.index), min(n, len(g))):
            picked.add(i)
    n_picked = len(picked)
    print(f"分层抽样: {n_picked} 条 (长评平台 {cell_stat['long']} 层 @{RATE_LONG:.0%}, "
          f"短文本平台 {cell_stat['short']} 层 @{RATE_SHORT:.0%})")

    # ---------- 6. 总量裁剪：压回 330~380 ----------
    total = n_must + n_picked
    print(f"\n裁剪前总量: {total} 条")

    if total > TARGET_MAX:
        budget = TARGET_MAX - n_must
        keep = set()
        if budget > 0:
            pick_df = pool.loc[pool.index.isin(picked)].sort_values("score", ascending=False)
            keep = set(pick_df.head(budget).index)
        removed = picked - keep
        picked = keep
        total = n_must + len(picked)
        print(f"超过上限 {TARGET_MAX}，按 score 从高到低裁掉抽样 {len(removed)} 条 → {total} 条")

    if not (TARGET_MIN <= total <= TARGET_MAX):
        print(f"!! 警告: 总量 {total} 不在目标区间 [{TARGET_MIN}, {TARGET_MAX}]，请检查规则/参数")
    print(f"最终复核量: {total} 条 ({total/len(df)*100:.1f}%)")

    # ---------- 7. 标记归属 ----------
    df = df.copy()
    df["queue_group"] = ""
    df["rule_hit"] = ""

    for i in df.index[is_must]:
        df.at[i, "queue_group"] = "必审"
        df.at[i, "rule_hit"] = describe_rule(i, is_neg, is_very_short, is_rt_conflict,
                                             is_low, is_close, is_mixed, is_long)
    for i in picked:
        df.at[i, "queue_group"] = "抽样"
        df.at[i, "rule_hit"] = describe_rule(i, is_neg, is_very_short, is_rt_conflict,
                                             is_low, is_close, is_mixed, is_long)

    all_idx = list(set(df.index[is_must]) | picked)
    queue = df[df.index.isin(all_idx)].copy()
    queue["review_rank"] = range(1, len(queue) + 1)

    queue["manual_sentiment"] = ""
    queue["manual_note"] = ""

    # ---------- 8. 输出 xlsx ----------
    must_df = queue[queue["queue_group"] == "必审"].copy()
    sup_df = queue[queue["queue_group"] == "抽样"].copy()

    wb = Workbook()

    ws0 = wb.active
    ws0.title = "操作说明"
    notes = [
        "Film 层人工复核清单 — 使用说明",
        "",
        "1. 本清单由 03a_build_review_queue_film.py 生成，数据来自 03_sentiment_all.csv，不重跑模型。",
        "2. 共两个复核表：『核心复核清单』(必审) 与 『补充抽审清单』(抽样)。",
        "3. 只允许填写两列（黄色）：manual_sentiment（下拉：positive/neutral/negative/mixed/other）和 manual_note（备注）。",
        "4. 不要修改 sentiment_final —— 它不在清单里，由后续脚本根据你的复核结果自动生成。",
        "5. 复核口径建议：以评论整体观感为准；model 的 sentiment_pred 只是参考，可能与你的判断不同。",
        "6. record_id 是回填唯一键，请勿修改。",
        "",
        "规则回顾（Film 版，2026-08-14 定稿）：",
        "必审 = 负面 ∪ 极端短文本(<10字) ∪ RT评分冲突。负面是研究核心，全量必审。",
        "RT评分冲突 = RT 原生观众评分与模型预测矛盾：score>=4.0 却判 negative，或 score<=2.0 却判 positive，直接必审。",
        "抽样 = 低置信(<0.65) / 类间差(<0.20) / 混合情感 / 超长(>=1000字) 四类候选池，",
        "       按平台形式加权分层抽样（长评平台 MAL/AniList 8%，短文本平台 Reddit/X/YouTube/RT 20%）。",
        "分层粒度 = 平台 × 作品 × 情感，每层至少 1 条，保证覆盖不偏重大平台。",
        f"最终复核量目标 {TARGET_MIN}~{TARGET_MAX} 条。",
    ]
    for ln in notes:
        ws0.append([ln])
    ws0.column_dimensions["A"].width = 120

    def write_review_sheet(wb, name, data, sort_col="review_rank"):
        ws = wb.create_sheet(name)
        cols = CONTEXT_COLS + ["queue_group", "rule_hit", "review_rank",
                               "manual_sentiment", "manual_note"]
        ws.append(cols)
        header_fill = PatternFill("solid", fgColor="4472C4")
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = header_fill
        for _, r in data.sort_values(sort_col).iterrows():
            ws.append([r[c] for c in cols])

        yellow = PatternFill("solid", fgColor="FFF2CC")
        dv = DataValidation(type="list",
                            formula1='"positive,neutral,negative,mixed,other"',
                            allow_blank=True)
        ws.add_data_validation(dv)
        i_man = cols.index("manual_sentiment") + 1
        i_note = cols.index("manual_note") + 1
        for r in range(2, 2 + len(data)):
            ws.cell(row=r, column=i_man).fill = yellow
            ws.cell(row=r, column=i_note).fill = yellow
            dv.add(ws.cell(row=r, column=i_man))
        for c in ws.columns:
            head = c[0]
            if head is None or getattr(head, "value", None) is None:
                continue
            try:
                letter = head.column_letter
            except AttributeError:
                continue
            if letter == "J":
                ws.column_dimensions[letter].width = 80
            elif letter == "E":
                ws.column_dimensions[letter].width = 26
            else:
                ws.column_dimensions[letter].width = 15
        ws.freeze_panes = "A2"
        return ws

    write_review_sheet(wb, "核心复核清单", must_df)
    write_review_sheet(wb, "补充抽审清单", sup_df)

    ws_r = wb.create_sheet("规则统计")
    stats = [
        ["必审-负面", int(is_neg.sum())],
        ["必审-极端短文本", int(is_very_short.sum())],
        ["必审-RT评分冲突", int(is_rt_conflict.sum())],
        ["必审-RT高星却负面(>=4.0)", int(is_rt_high_neg.sum())],
        ["必审-RT低星却正面(<=2.0)", int(is_rt_low_pos.sum())],
        ["必审-并集(去重)", n_must],
        ["抽样候选池-低置信(非必审)", int((is_low & ~is_must).sum())],
        ["抽样候选池-类间差(非必审)", int((is_close & ~is_must).sum())],
        ["抽样候选池-混合(非必审)", int((is_mixed & ~is_must).sum())],
        ["抽样候选池-超长(非必审)", int((is_long & ~is_must).sum())],
        ["抽样候选池-并集", n_pool],
        ["最终抽样数", len(picked)],
        ["最终复核总量", total],
        ["占全量比例", f"{total/len(df)*100:.1f}%"],
    ]
    ws_r.append(["统计项", "数量"])
    for row in stats:
        ws_r.append(row)
    ws_r.column_dimensions["A"].width = 40
    ws_r.column_dimensions["B"].width = 12

    ws_c = wb.create_sheet("平台×作品覆盖情况")
    cov = df.groupby(["source", "anime_name"]).size().rename("总数")
    q = queue.groupby(["source", "anime_name"]).size().rename("复核数")
    must_c = must_df.groupby(["source", "anime_name"]).size().rename("必审")
    sup_c = sup_df.groupby(["source", "anime_name"]).size().rename("抽样")
    cov_tbl = pd.DataFrame(cov).join(pd.DataFrame(q)).join(pd.DataFrame(must_c)).join(pd.DataFrame(sup_c))
    cov_tbl = cov_tbl.fillna(0).astype({"总数": int, "复核数": int, "必审": int, "抽样": int})
    cov_tbl["覆盖率%"] = (cov_tbl["复核数"] / cov_tbl["总数"] * 100).round(1)
    cov_tbl = cov_tbl.sort_index()
    ws_c.append(["source", "anime_name", "总数", "复核数", "必审", "抽样", "覆盖率%"])
    for row in dataframe_to_rows(cov_tbl.reset_index(), index=False, header=False):
        ws_c.append(list(row))
    for c in ws_c.columns:
        try:
            letter = c[0].column_letter
        except AttributeError:
            continue
        ws_c.column_dimensions[letter].width = 12

    wb.save(OUT_XLSX)
    print(f"\n已生成 {OUT_XLSX}")
    print(f"  核心复核清单: {len(must_df)} 条")
    print(f"  补充抽审清单: {len(sup_df)} 条")
    print("\n完成。")


if __name__ == "__main__":
    main()
