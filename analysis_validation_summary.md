# 分析验收总结（Analysis Validation Summary）

> 验收对象：封版后的 `analytical_series.csv` / `analytical_film.csv` / `analytical_all.csv` + `07_association_analysis.py`
> 验收日期：2026-08-19
> 结论：**4 处问题已发现并修正**，修正后所有关键结论可复现、口径一致，可以据此进入报告写作。

---

## 一、逐项验收结果（10 项 checklist）

| # | 检查项 | 结果 | 说明 |
|---|--------|------|------|
| 1 | 情感统一用 final_sentiment | ✅ 通过 | 全部脚本用 `sentiment_final`（人工复核后终值），无一处偷用 `sentiment_pred`。⚠ 唯一遗留：字段名是 `sentiment_final`，GPT方案文档写的是 `final_sentiment`，**命名待对齐**（建议保留现状 `sentiment_final`，报告里统一口径即可） |
| 2 | other 统一排除 | ⚠ 修正后通过 | 情感分析一直排除；**主题关联分析原先漏排 other，已修正**（分母现在与 05 管线一致，排除 16/73 条 other） |
| 3 | pooled / platform_balanced / all_platform_equal 三口径 | ✅ 通过 | 04 脚本实现正确（n≥30 且 覆盖≥3），三口径数字从封版 CSV 重算**完全一致**。正文主结论用 platform_balanced，附 pooled；all_platform_equal 仅敏感性 |
| 4 | 平台准入 n≥30 且 覆盖作品≥3 | ⚠ 修正后通过 | 07 原先只查 n≥30，**漏了覆盖≥3**，导致 Film 的 Reddit(66条/仅覆盖《哪吒》1部) 被误纳入。已修正，准入现在与 04 完全一致 |
| 5 | χ² 输出最小期望频数 + 期望<5 比例 | ✅ 通过 | 每次检验都打印 `min_expected` 和 `sparse_ratio`，超 20% 自动标 ⚠ |
| 6 | Cramér's V 与 χ² 一一对应 | ✅ 通过 | 每个 χ² 都配套 `V = sqrt(χ²/(n·min(r-1,c-1)))`，无遗漏 |
| 7 | 主题多标签不 explode | ✅ 通过 | 12 主题各自 presence/absence 二值独立检验 + Bonferroni 校正(α=0.05/12)，未做 explode |
| 8 | Series vs Film 只用共有充分平台 | ⚠ 修正后通过 | 原先用全部数据；已修正为只比**共有且覆盖充分平台 = YouTube + X** |
| 9 | Ne Zha shared-title 单独输出 | ❌→✅ 已补 | 原先缺失，已新增（同一部《哪吒》跨平台对比） |
| 10 | 关键样本量/比例可复现 | ✅ 通过 | 所有关键数字（样本量、三口径、χ²）均已从最终 CSV 重算验证 |

---

## 二、发现并已修正的 4 个问题

1. **【重要】Film 平台准入漏了"覆盖作品≥3"**：`07` 原只按 `n≥30` 准入，把 Reddit（Film 里 66 条但**只覆盖《哪吒》1 部**）当成正式平台参与 Film 情感 χ²。这会引入"作品效应"（Reddit 的情感其实是"Reddit 上《哪吒》的情感"，不是"Reddit 对电影的整体态度"）。→ 已改为 `n≥30 且 覆盖≥3`，Film 正式平台 = **RT / X / YouTube**，Reddit 只进 shared-title。

2. **【重要】主题关联分析没排除 other**：`analyze_topic_platform` 原先没过滤 `sentiment_final != "other"`，导致 other（无关/引战/误命中）混进主题命中率分母，压低命中率。→ 已修正，与 05 管线"基数排除 other"口径一致。

3. **Series vs Film 比较用了全部平台**：原先 concat 全部数据直接比，但 Film 有 RT（Series 没有）、Series 有 MAL（Film 只有 9 条），平台构成不同会污染 form 比较。→ 已改为**只比共有且覆盖充分平台（YouTube + X）**。

4. **Ne Zha shared-title 缺失**：GPT方案点明要做，原 07 没有。→ 已补充（见关键发现 ③）。

---

## 三、最终可用于报告的关键发现（已修正口径）

> 以下数字全部从封版 CSV 重算验证，可直接进报告。

### ① 海外平台明显分两类（Series 与 Film 高度一致）

**Series**（准入 4 平台，排除 other，χ²=208.81, df=9, p<0.001, **Cramér's V=0.242**，最小期望 5.14）：

| 平台 | 正面率 | 中性率 | 定位 |
|------|--------|--------|------|
| MAL | 82.2% | 9.8% | 评分/长评型 |
| YouTube | 81.4% | 16.2% | 视频型（夸赞多） |
| Reddit | 45.1% | 42.2% | 讨论型 |
| X | 45.2% | 49.5% | 讨论型 |

**Film**（准入 3 平台，χ²=182.02, df=6, p<0.001, **V=0.304**，最小期望 6.84）：

| 平台 | 正面率 | 中性率 | 定位 |
|------|--------|--------|------|
| RT | 84.9% | 3.6% | 评分/长评型 |
| YouTube | 74.3% | 21.7% | 视频型 |
| X | 42.7% | 51.7% | 讨论型 |

**稳健性**：正面率二值 χ² Series V=0.382、Film V=0.343，均显著。
**标准化残差**（|z|>2.58 很强）：MAL/RT/YouTube 正面格显著偏多；X/Reddit 中性格显著偏多。

> 报告写法：平台分「评分/长评型（MAL、RT）— 视频型（YouTube）— 讨论型（X、Reddit）」三档。正面率在 42%~85% 之间，差异巨大且显著。

### ② Series vs Film 情感分布无显著差异

只用共有充分平台（**YouTube + X**）：χ²=2.03, df=3, **p=0.5653**, V=0.038（最小期望 10.38）。

- 结论：**"系列动画 vs 动画电影"这个媒介形式，本身不驱动海外情感差异**。情感差异更多来自平台生态、具体作品和评论体裁。
- 写法用「提示/可能」，不写因果。这是一个"好的负面结果"。

### ③ Ne Zha shared-title 稳健性验证（控制作品后平台差异仍在）

同一部《哪吒》(2019)，跨 5 平台（排除 other 后：RT 179 / YouTube 81 / X 66 / Reddit 58 / MAL 9 仅展示）：

| 平台 | 正面率（同一部《哪吒》） |
|------|------|
| RT | 83.2% |
| YouTube | 74.1% |
| Reddit | 46.6% |
| X | 37.9% |

χ²=93.75, df=9, p<0.001, **V=0.285**（⚠ 最小期望 2.87，mixed/negative 格稀疏，p 值谨慎解读，但**正面率二值对比稳健**）。

- 结论：**控制作品后，平台情感差异依然存在**（RT 比 X 高 45 个百分点）→ 说明"平台差异"不是"作品选择差异"造成的，是真实稳健的平台生态效应。这是报告里最有力的 robustness analysis。

### ④ 评论长度 confound（主题差异 ≠ 受众偏好差异）

- MAL（长评，均值 ~1830 字）/ RT（长评 ~5203 字）在**所有主题**命中率都最高；X（短评 ~120 字）几乎不命中。
- Series 11/12 主题、Film 8/12 主题在"主题×平台"检验中显著（Bonferroni α=0.00417），但**这种差异主要反映"长评 vs 短评"的体裁差异，而非平台受众兴趣差异**。
- 报告必须单开一小节说明这个 confound，否则会把"MAL 用户更关心剧情"这类误读写进去。

---

## 四、关键样本量与三口径（可复现，供报告引用）

| 层 | 总样本 | 有效(排除other) | 作品数 | 平台 |
|----|--------|------|--------|------|
| Series | 1233 | 1217（other 16） | 6 | YouTube 420 / X 314 / MAL 264 / Reddit 208 / AniList 27 |
| Film | 1125 | 1052（other 73） | 7 | YouTube 488 / X 283 / RT 278 / Reddit 66 / MAL 9 / AniList 1 |

**三口径情感分布（%）**：

| 情感 | Series pooled | Series balanced | Film pooled | Film balanced |
|------|------|------|------|------|
| positive | 66.6 | **63.5** | 68.6 | **67.3** |
| neutral | 27.3 | 29.4 | 24.9 | 25.7 |
| negative | 3.7 | 4.4 | 3.0 | 3.3 |
| mixed | 2.5 | 2.7 | 3.4 | 3.7 |

> balanced = 正文主口径（Series 准入 MAL/Reddit/X/YouTube；Film 准入 RT/X/YouTube）。all_platform_equal 仅敏感性，正文不引。

---

## 五、遗留待对齐（非 bug，写报告前需拍板）

1. **字段命名**：数据里是 `sentiment_final`，GPT方案写 `final_sentiment`。建议统一为 `sentiment_final`（下游 04/05 已依赖此名），报告里说明即可。
2. **Film 的 MAL/AniList**（9/1 条）与 **Series 的 AniList**（27 条，覆盖仅 2 部）：可展示、不进任何正式推断。
3. **Ne Zha shared-title 的 4 类 χ² 稀疏**（min_expected 2.87）：报告里主引"正面率二值对比"，4 类 χ² 只作辅助。
