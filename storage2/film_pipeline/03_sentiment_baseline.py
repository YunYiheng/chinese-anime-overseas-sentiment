# -*- coding: utf-8 -*-
"""
03_sentiment_baseline.py
========================
情感分析基线版（本地多语言模型，不调 LLM API）。

输入 : 02_cleaned_valid_lang.csv（1195 条，原文件不被修改）
模型 : cardiffnlp/twitter-xlm-roberta-base-sentiment-multilingual
       （多语言 XLM-RoBERTa，支持 100 语，情感标签 negative/neutral/positive）
输出 :
  1. 03_sentiment_all.csv              全量 1195 条 + 全部情感字段
  2. sentiment_review.xlsx             需要人工复核的样本清单（可回填审核结果）
  3. sentiment_baseline_summary.xlsx   基线统计汇总（平台/作品/语言 × 情感）

用法 :
  python 03_sentiment_baseline.py             # 全量跑
  python 03_sentiment_baseline.py --smoke     # 冒烟测试：随机 50 条 + 打印标签映射核对

核心设计（与 ChatGPT 方案 3 的"升级版混合方案"一致）：
  - 本地模型跑全量，免费、离线、可复现（不消耗 API 费用 / key）
  - 模型置信度低 / 类间差距小 / 混合情感 / 负面 / 超长 / 低频语言 / 高互动样本
    → 标记 needs_review=1 进入人工复核，人工结果回填 manual_sentiment
  - 周报等下游消费 sentiment_final（默认 = 模型预测，人工复核后可改）
  - 模型不是最终裁判，人工复核才是兜底 —— 这是"混合方案"准确性的保障
"""

import sys
import re
import random
import argparse
from collections import Counter

try:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 控制台默认 GBK，避免中文打印报错
except Exception:
    pass

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.worksheet.datavalidation import DataValidation

# ============================== 配置区 ==============================
INPUT_CSV = "02_cleaned_valid_lang.csv"
MODEL_NAME = "cardiffnlp/twitter-xlm-roberta-base-sentiment-multilingual"

# 该模型官方标签映射（脚本运行时还会从 config 动态读取核对）
EXPECTED_LABELS = {"LABEL_0": "negative", "LABEL_1": "neutral", "LABEL_2": "positive"}

# 长文本切分：单句超过该字符数 → 按块再切（块大小 ≈ 400 字符，安全低于 512 token 上限）
CHUNK_CHARS = 400
MIN_UNIT_LEN = 2          # 太短的句子片段直接丢弃，避免噪音单元

# 人工复核触发阈值
CONF_THRESHOLD = 0.65     # 最高概率 < 0.65  → 低置信
CLOSE_CALL = 0.20         # 前二概率差 < 0.20 → 类间差距小
VERY_LONG_CHARS = 1000    # 超长文本判定
LOW_FREQ_LANG_MIN = 15    # 语言组数量 < 15 → 低频语言（模型训练语料覆盖不足）
STRAT_SAMPLE_RATE = 0.10  # 剩余高置信样本分层抽样复核比例
STRAT_SEED = 42           # 抽样随机种子，保证可复现
SMOKE_N = 50              # 冒烟测试随机条数

# 输出文件名（冒烟模式加 smoke_ 前缀，避免覆盖正式输出）
OUT_ALL = "03_sentiment_all.csv"
OUT_REVIEW = "sentiment_review.xlsx"
OUT_SUMMARY = "sentiment_baseline_summary.xlsx"

# ============================== 文本切分 ==============================
def segment_text(text: str):
    """
    把一段文本切成"分析单元"列表：
      1) 先按段落（换行）和句子（. ! ? 以及 。！？，保留标点）切分
      2) 单句超长（> CHUNK_CHARS）再按 CHUNK_CHARS 字符切块
    这样长文本逐句/逐块分类后聚合，不会只截取开头。
    """
    # 分句：在 . ! ? 或 中文句读 之后切分；换行也算句子边界
    parts = re.split(r"(?<=[.!?。！？])|\n+", text)
    units = []
    for part in parts:
        part = part.strip()
        if len(part) < MIN_UNIT_LEN:
            continue
        if len(part) > CHUNK_CHARS:
            # 单句超长 → 按字符切块（安全低于 XLM-R 512 token 上限）
            for i in range(0, len(part), CHUNK_CHARS):
                chunk = part[i:i + CHUNK_CHARS].strip()
                if len(chunk) >= MIN_UNIT_LEN:
                    units.append(chunk)
        else:
            units.append(part)
    return units


def normalize_label(lbl):
    """
    把模型输出的标签归一化成规范名（positive/neutral/negative）。
    兼容两种输出格式：
      - 老格式 'LABEL_0'/'LABEL_1'/'LABEL_2'（按官方映射表转换）
      - 新格式 'positive'/'Negative'/'NEUTRAL' 等（直接转小写）
    """
    if lbl in EXPECTED_LABELS:
        return EXPECTED_LABELS[lbl]
    return str(lbl).lower()


def parse_output(pipe_out):
    """
    解析 pipeline(top_k=None) 输出。
    pipe_out: 一条文本的结果，形如
        [{'label': 'LABEL_2' 或 'positive', 'score': 0.9}, ...]
    返回 (prob_pos, prob_neu, prob_neg)。
    """
    scores = {}
    for d in pipe_out:
        scores[normalize_label(d["label"])] = float(d["score"])
    return (scores.get("positive", 0.0),
            scores.get("neutral", 0.0),
            scores.get("negative", 0.0))


# ============================== 主流程 ==============================
def main():
    ap = argparse.ArgumentParser(description="情感分析基线（本地多语言模型）")
    ap.add_argument("--smoke", action="store_true", help="冒烟测试：随机 50 条 + 核对标签映射")
    args = ap.parse_args()
    smoke = args.smoke

    print("=" * 60)
    print("情感分析基线（本地多语言模型）")
    print(f"模式: {'冒烟测试 ' + str(SMOKE_N) + ' 条' if smoke else '全量'}")
    print(f"模型: {MODEL_NAME}")
    print("=" * 60)

    # ---------- 1. 读数据 ----------
    df = pd.read_csv(INPUT_CSV, encoding="utf-8-sig")
    print(f"\n读取 {INPUT_CSV}: {len(df)} 条")

    if smoke:
        rng = random.Random(STRAT_SEED)
        idx = rng.sample(list(df.index), SMOKE_N)
        df = df.loc[idx].copy()
        print(f"冒烟模式：随机抽取 {SMOKE_N} 条")

    # ---------- 2. 加载模型 ----------
    print("\n加载模型（首次运行会自动下载 ~1.1GB，之后走本地缓存）...")
    from transformers import pipeline

    # top_k=None → 每个输入返回全部 3 个标签的概率，而不是只给最高
    # use_safetensors=True → 加载 model.safetensors 而非 pytorch_model.bin
    #   （本机 torch 2.5.1 低于 transformers 5.14 要求的 2.6，torch.load 被安全策略拦截，
    #    而 safetensors 路径不受此限制，且加载更快）
    pipe = pipeline(
        "text-classification",
        model=MODEL_NAME,
        truncation=True,
        max_length=512,
        top_k=None,
        model_kwargs={"use_safetensors": True},
    )

    # 核对标签映射：从模型 config 动态读取，和官方预期对照
    id2label = pipe.model.config.id2label          # {0:'Negative',1:'Neutral',2:'Positive'}
    label_names = {}                                # {'positive': 'LABEL_2', ...}
    for label_id in sorted(id2label):
        cls = id2label[label_id].lower()
        if cls in ("positive", "neutral", "negative"):
            label_names[cls] = f"LABEL_{label_id}"
    print("标签映射核对:")
    for cls, lab in sorted(label_names.items()):
        print(f"  {cls:8s} <- {lab:8s} (config id2label={id2label[int(lab.split('_')[1])]})")
        exp = [k for k, v in EXPECTED_LABELS.items() if v == cls][0]
        flag = "OK" if lab == exp else f"!! 与官方预期 {exp} 不一致"
        print(f"     与官方预期对照: {flag}")
    if smoke:
        print("\n[冒烟] 标签映射核对完成：请确认上面三行均为 OK。")

    # ---------- 3. 逐条切分 + 分类 + 聚合 ----------
    print("\n开始分类...")
    records = []           # 每条评论的结果行
    units_total = 0
    n_comment = 0

    for i, row in df.iterrows():
        text = str(row["content_clean"])
        units = segment_text(text)
        units_total += len(units)

        # 批量推理单条的全部单元（一条评论单元数通常很少）
        if not units:      # 理论上不会发生（valid 数据），兜底
            units = [" "]
        out = pipe(units, batch_size=64, top_k=None)

        # 每个单元的 (pos, neu, neg, pred, pred_prob)
        unit_res = []
        for u, o in zip(units, out):
            pp, pn, pn2 = parse_output(o)
            pred = max(("positive", pp), ("neutral", pn), ("negative", pn2),
                       key=lambda x: x[1])
            unit_res.append((pp, pn, pn2, pred[0], pred[1]))

        # 聚合：平均概率
        arr = np.array([[u[0], u[1], u[2]] for u in unit_res])
        mean = arr.mean(axis=0)
        prob_pos, prob_neu, prob_neg = float(mean[0]), float(mean[1]), float(mean[2])
        sentiment_pred = ["positive", "neutral", "negative"][int(np.argmax(mean))]
        sentiment_score = prob_pos - prob_neg          # 连续分数 ∈ [-1, 1]

        # 混合情感候选：存在 1 个及以上置信(≥0.5)的正面句 且 存在置信的负面句
        has_pos_sent = any(u[3] == "positive" and u[4] >= 0.5 for u in unit_res)
        has_neg_sent = any(u[3] == "negative" and u[4] >= 0.5 for u in unit_res)
        mixed_candidate = 1 if (has_pos_sent and has_neg_sent) else 0

        records.append({
            # 注意：不放 record_id —— df 已有该列，若重复会出现列名冲突
            # （concat 后两个 record_id，review 清单按列名取值会错位）
            "sentiment_pred": sentiment_pred,
            "sentiment_score": round(sentiment_score, 4),
            "prob_positive": round(prob_pos, 4),
            "prob_neutral": round(prob_neu, 4),
            "prob_negative": round(prob_neg, 4),
            "n_segments": len(unit_res),
            "mixed_candidate": mixed_candidate,
        })
        n_comment += 1
        if n_comment % 200 == 0:
            print(f"  已处理 {n_comment} 条...")

    res = pd.DataFrame(records)
    df = df.reset_index(drop=True)
    res = res.reset_index(drop=True)
    out = pd.concat([df, res], axis=1)
    print(f"完成：{n_comment} 条，切分单元总数 {units_total}")

    # ---------- 4. 人工复核筛选 ----------
    print("\n计算复核标记...")
    # 4.1 高互动阈值：按 source × anime 组内 score 的 90 分位（组太小则退回 source 级）
    hi_eng = pd.Series(False, index=out.index)
    for (src, anime), g in out.groupby(["source", "anime_name"]):
        if len(g) >= 5:
            thr = g["score"].quantile(0.90)
        else:
            thr = out[out["source"] == src]["score"].quantile(0.90)
        hi_eng.loc[g.index] = g["score"] >= thr

    # 4.2 低频 / 未知 / 混合语言
    lang_counts = out["lang_group"].value_counts()
    low_freq_lang = out["lang_group"].map(
        lambda lg: (lang_counts.get(lg, 0) < LOW_FREQ_LANG_MIN)
                   or lg in ("未知", "中英混合"))

    # 4.3 逐条判定复核原因
    max_prob = out[["prob_positive", "prob_neutral", "prob_negative"]].max(axis=1)
    sorted_probs = np.sort(out[["prob_positive", "prob_neutral", "prob_negative"]].values, axis=1)
    prob_diff = sorted_probs[:, -1] - sorted_probs[:, -2]

    review_reason = []
    for i, r in out.iterrows():
        rs = []
        if max_prob.loc[i] < CONF_THRESHOLD:
            rs.append("低置信")
        if prob_diff[i] < CLOSE_CALL:
            rs.append("类间差距小")
        if r["mixed_candidate"] == 1:
            rs.append("混合情感")
        if hi_eng.loc[i]:
            rs.append("高互动")
        if r["sentiment_pred"] == "negative":
            rs.append("负面样本")
        if r["content_length"] >= VERY_LONG_CHARS:
            rs.append("超长文本")
        if low_freq_lang.loc[i]:
            rs.append("低频/未知/混合语言")
        review_reason.append("; ".join(rs))
    out["review_reason_base"] = review_reason

    # 4.4 剩余（未被上述规则命中）样本按 source×anime 分层随机抽 10%
    stratified = pd.Series(False, index=out.index)
    remaining = out[out["review_reason_base"] == ""]
    if len(remaining) > 0:
        rng = random.Random(STRAT_SEED)
        for (src, anime), g in remaining.groupby(["source", "anime_name"]):
            n_sample = max(1, int(np.ceil(len(g) * STRAT_SAMPLE_RATE)))
            pick = rng.sample(list(g.index), min(n_sample, len(g)))
            stratified.loc[pick] = True

    # 4.5 汇总 review_reason + needs_review + 优先级
    def make_final_reason(base, is_strat):
        if base:
            return base
        if is_strat:
            return "分层抽样10%"
        return ""

    final_reason = [make_final_reason(b, s) for b, s in zip(out["review_reason_base"], stratified)]
    out["review_reason"] = final_reason
    out["needs_review"] = (pd.Series(final_reason) != "").astype(int)

    def priority(rs):
        if not rs:
            return ""
        if any(k in rs for k in ["混合情感", "负面样本", "超长文本", "低频/未知/混合语言"]):
            return "high"
        if rs == "分层抽样10%":
            return "low"
        return "medium"

    out["review_priority"] = [priority(rs) for rs in final_reason]
    out.drop(columns=["review_reason_base"], inplace=True)

    # ---------- 5. 人工复核相关字段（初始占位） ----------
    out["sentiment_model"] = MODEL_NAME
    out["manual_sentiment"] = ""      # 人工填写：positive / neutral / negative / mixed
    out["manual_note"] = ""           # 人工备注
    out["sentiment_final"] = out["sentiment_pred"]  # 默认=模型预测，人工复核后可覆盖

    # 字段顺序整理：情感字段放最后
    base_cols = [c for c in out.columns if c not in (
        "sentiment_model", "sentiment_pred", "sentiment_score", "prob_positive",
        "prob_neutral", "prob_negative", "n_segments", "mixed_candidate",
        "needs_review", "review_reason", "review_priority", "manual_sentiment",
        "manual_note", "sentiment_final")]
    senti_cols = ["sentiment_model", "sentiment_pred", "sentiment_score",
                  "prob_positive", "prob_neutral", "prob_negative", "n_segments",
                  "mixed_candidate", "needs_review", "review_reason",
                  "review_priority", "manual_sentiment", "manual_note",
                  "sentiment_final"]
    out = out[base_cols + senti_cols]

    # ---------- 6. 输出 ----------
    prefix = "smoke_" if smoke else ""
    out_all = prefix + OUT_ALL
    out_review = prefix + OUT_REVIEW
    out_summary = prefix + OUT_SUMMARY

    # 6.1 全量 CSV（utf-8-sig，Excel 打开不乱码）
    out.to_csv(out_all, index=False, encoding="utf-8-sig")
    print(f"\n[1/3] 全量情感结果 -> {out_all}  ({len(out)} 条)")

    # 6.2 人工复核清单 xlsx
    review_df = out[out["needs_review"] == 1].copy()
    review_cols = ["record_id", "anime_name", "source", "author", "post_time", "score",
                   "lang_group", "content_length", "content_clean",
                   "sentiment_pred", "sentiment_score", "prob_positive", "prob_neutral",
                   "prob_negative", "mixed_candidate", "review_reason", "review_priority",
                   "manual_sentiment", "manual_note", "sentiment_final"]
    wb = Workbook()
    ws = wb.active
    ws.title = "复核清单"

    # 说明行（顶部）
    note_lines = [
        f"人工复核清单（共 {len(review_df)} 条）—— 请只填黄色列：manual_sentiment（下拉选择）、manual_note、sentiment_final",
        "规则：低置信(最高概率<0.65)、类间差距小(前二差<0.20)、混合情感、高互动(平台×作品前10%)、负面、超长(>=1000字)、低频/未知/混合语言、分层抽样10%",
        "sentiment_final 已预填=模型预测；若你人工判断不同，请覆盖它。周报后续引用 sentiment_final。",
        "",
    ]
    for ln in note_lines:
        ws.append([ln])
    ws.merge_cells("A1:T1")
    ws.merge_cells("A2:T2")
    ws.merge_cells("A3:T3")
    ws.merge_cells("A4:T4")
    ws.cell(row=1, column=1).font = Font(bold=True, color="C00000")

    # 表头
    start_row = ws.max_row + 1
    ws.append(review_cols)
    header_fill = PatternFill("solid", fgColor="4472C4")
    for cell in ws[start_row]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill

    # 数据
    for _, r in review_df[review_cols].iterrows():
        ws.append(list(r.values))

    # 手动复核列加黄色底 + 下拉
    yellow = PatternFill("solid", fgColor="FFF2CC")
    dv = DataValidation(type="list", formula1='"positive,neutral,negative,mixed,other"', allow_blank=True)
    ws.add_data_validation(dv)
    col_manual = review_cols.index("manual_sentiment") + 1
    col_note = review_cols.index("manual_note") + 1
    col_final = review_cols.index("sentiment_final") + 1
    for r in range(start_row + 1, start_row + 1 + len(review_df)):
        ws.cell(row=r, column=col_manual).fill = yellow
        ws.cell(row=r, column=col_note).fill = yellow
        ws.cell(row=r, column=col_final).fill = yellow
        dv.add(ws.cell(row=r, column=col_manual))
    # 列宽（content 列设宽，方便看全文）；跳过顶部合并单元格（MergedCell 无 column_letter）
    for c in ws.columns:
        head = c[0]
        if head is None or getattr(head, "value", None) is None:
            continue
        try:
            letter = head.column_letter
        except AttributeError:
            continue
        if letter == "I":   # content_clean
            ws.column_dimensions[letter].width = 80
        elif letter == "D": # author
            ws.column_dimensions[letter].width = 28
        else:
            ws.column_dimensions[letter].width = 16
    ws.freeze_panes = f"A{start_row + 1}"

    # 说明 sheet
    ws2 = wb.create_sheet("说明")
    ws2.append(["字段说明"])
    for i, t in enumerate([
        "sentiment_pred: 模型主标签（positive/neutral/negative，三概率最大者）",
        "sentiment_score: prob_positive - prob_negative，范围[-1,1]，越大越正面",
        "mixed_candidate: 句子级既有正面又有负面(各自概率>=0.5) → 1",
        "needs_review: 1=进入本清单需要人工复核",
        "review_priority: high(混合/负面/超长/低频语言) / medium(低置信/类间差距/高互动) / low(分层抽样)",
        "manual_sentiment: 人工判定，下拉选择；manual_note: 备注",
        "sentiment_final: 最终口径，默认=模型预测，人工复核后覆盖",
    ], 1):
        ws2.append([t])
    ws2.column_dimensions["A"].width = 110

    wb.save(out_review)
    print(f"[2/3] 复核清单 -> {out_review}  ({len(review_df)} 条需复核)")

    # 6.3 基线汇总 xlsx
    wbs = Workbook()
    wbs.remove(wbs.active)

    def write_sheet(wb2, name, df2):
        ws = wb2.create_sheet(name)
        for row in dataframe_to_rows(df2, index=False, header=True):
            ws.append(row)
        for c in ws.columns:
            head = c[0]
            if head is None or getattr(head, "value", None) is None:
                continue
            try:
                letter = head.column_letter
            except AttributeError:
                continue
            ws.column_dimensions[letter].width = max(12, min(40, len(str(head.value)) + 4))
        return ws

    write_sheet(wbs, "总览", pd.DataFrame({
        "指标": ["样本总数", "需人工复核数", "复核占比", "混合情感候选数", "平均切分单元数"],
        "数值": [len(out), int(out["needs_review"].sum()),
                f"{out['needs_review'].mean()*100:.1f}%",
                int(out["mixed_candidate"].sum()),
                f"{out['n_segments'].mean():.1f}"]}))
    write_sheet(wbs, "情感分布", pd.DataFrame(
        out["sentiment_pred"].value_counts()).reset_index().rename(
        columns={"index": "sentiment", "sentiment_pred": "条数"}))
    write_sheet(wbs, "平台×情感", pd.crosstab(out["source"], out["sentiment_pred"]).reset_index())
    write_sheet(wbs, "作品×情感", pd.crosstab(out["anime_name"], out["sentiment_pred"]).reset_index())
    write_sheet(wbs, "语言×情感", pd.crosstab(out["lang_group"], out["sentiment_pred"]).reset_index())
    write_sheet(wbs, "复核原因统计", pd.DataFrame(
        [r.strip() for r in out.loc[out["needs_review"] == 1, "review_reason"]
         if isinstance(r, str) and r]
    ).value_counts().reset_index().rename(columns={"index": "复核原因", 0: "条数"}))
    write_sheet(wbs, "复核优先级", pd.DataFrame(
        out.loc[out["needs_review"] == 1, "review_priority"].value_counts()
    ).reset_index().rename(columns={"index": "优先级", "review_priority": "条数"}))
    write_sheet(wbs, "标签映射", pd.DataFrame(
        [(lab, id2label[int(lab.split('_')[1])]) for lab in sorted(label_names.values())],
        columns=["模型标签", "含义"]))
    wbs.save(out_summary)
    print(f"[3/3] 基线汇总 -> {out_summary}")

    if smoke:
        print("\n[冒烟] 抽样展示 5 条:")
        sample = out.sample(5, random_state=STRAT_SEED)
        for _, r in sample.iterrows():
            txt = str(r["content_clean"])
            txt = txt[:60] + ("..." if len(txt) > 60 else "")
            print(f"  pred={r['sentiment_pred']:8s} pos={r['prob_positive']:.2f} "
                  f"neu={r['prob_neutral']:.2f} neg={r['prob_negative']:.2f} "
                  f"mixed={r['mixed_candidate']} | {txt}")

    print("\n完成。")


if __name__ == "__main__":
    main()
