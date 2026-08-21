# Dashboard 全局验收报告

- 验收日期：2026-08-21
- 范围：`dashboard/` 全部（`app.py` / `data_loader.py` / `analytics.py` / `templates/` / `static/`）
- 方法：代码静态审查 + Flask test client 全端点实测 + 封版文件结构核对（未起真实浏览器，控制台 JS 错误需人工 F12 复核）
- 结论：**可交付**。必须修复仅 1 项（ECharts resize），其余为低优先级优化。

---

## 一、数据口径一致性（核心，全部通过）

| 检查项 | 结论 |
|---|---|
| 三封版 CSV 列名 | ✅ `analytical_all/series/film.csv` 均 19 列，含 `global_record_id/anime_name/work_form/source/post_time/score/content/sentiment_final/topic/page_url`，与 `analytics.py` 读取字段一一对应 |
| other 口径 | ✅ `sentiment_final` 共 89 条 other（series 16 + film 73），与 `get_kpis` 注释「含 other 89 条」一致 |
| KPI 实测 | ✅ total 2358 / series_main 1217 / film_main 1052 / 平台 6 / Series 作品 6 / Film 作品 7 |
| 情感主口径 | ✅ 「三口径对比」sheet 的 `情感` 列为英文 `positive/neutral/mixed/negative`，`sentiment_koujing` 用前缀匹配 `platform_balanced_*` / `pooled_*` 正确；Series 63.47/29.43/2.70/4.39、Film 67.28/25.68/3.69/3.35，与报告正文一致 |
| 07 关联 xlsx | ✅ 10 个 sheet 全在；`检验汇总` 5 行（Series/Film 平台×情感、Series vs Film、Ne Zha 二值/四分类）与 `_summary_row` 引用的名称逐一匹配 |
| 平台×情感/残差 sheet | ✅ 列名 `source/positive/neutral/negative/mixed` 与 `_df_to_rows` 一致 |
| 主题×平台 sheet | ✅ 列名 `主题/命中数/χ²/p/Bonf显著/Cramér's V/最高平台/最低平台` 与 `_topic_rows` 一致 |
| NeZha sheet | ✅ 列名 `source/positive/neutral/negative/mixed`，4 平台数据齐全 |

**结论**：看板不重算统计，所有数字直接来自封版文件，口径与报告无冲突。前端取值（`bal['positive']` 等）不会拿到 `undefined`。

## 二、六类验收结果

### 1. 功能一致性
- ✅ 四页导航统一在 `base.html` navbar（Overview / Series / Film / Association）。
- ✅ 卡片样式统一（`.card` + `box-shadow`），间距统一用 `g-3/mb-4`。
- ⚠️ 标题层级微不一致：`index.html` 卡片标题用 `<h5>`，`form.html` 三联动图/评论卡用 `<h6>`（`association.html` 四大块用 `<h5>` 属合理 section 级）。

### 2. 数据口径
- ✅ 情感主口径 platform_balanced 与筛选内 pooled 区分清晰：`form.html` 顶部 `balanced-strip` 提示条 + `form.js` 文案「下方三张联动图为当前筛选内 pooled 分布，与主口径不同，勿直接比较」。
- ✅ 未准入平台两层一致：图内灰色柱（`#b0bec5`）+ tooltip「（未准入）」+ 卡片说明文字「灰色柱 = 未准入平台」。

### 3. 交互
- ✅ 三筛选器（作品/平台/情感）+ 重置按钮 + 评论分页（prev/next disabled 正确）+ 总数联动（`共 N 条`）。
- ✅ 主题表「仅显示显著主题」默认勾选，Series/Film 切换正确（`topicSigOnly` 与 `topicForm` 联动）。
- ❌ **ECharts 窗口缩放后不 resize**（见「必须修复」）。

### 4. 视觉
- ✅ 热力图 tooltip 清楚（`平台 · 情感：z = x.xx`）；图例/轴标签齐全。
- ✅ 评论表 hover 高亮（`table-hover`）+ 长文本悬停（`title` 显示全文/原始时间）。
- ⚠️ 评论表 / 主题表无 sticky 固定表头（当前 20 行/页价值有限）。

### 5. 异常处理
- ✅ `/api/<form>/...` 非法 form 返回 404（`_check_form` 生效）。
- ✅ 空筛选 / 无结果：`platform_dist:[]`、`sentiment_dist` 全 0、评论表「无评论」，前端各渲染函数对空数据均有兜底（`|| 0`、空数组展开安全），不抛错。
- ⚠️ `/api/comments` 的 `form` 参数**未做校验**：`form=bogus` 静默返回 film 数据（200）而非 404（前端不会传非法值，属防御性缺失）。
- ⚠️ `favicon.ico` 404（`base.html` 无 icon link）。

### 6. 控制台 JS 错误
- ✅ 静态审查未见会导致运行时错误的路径：`bal` 4 个 key 已实测齐全、`renderResidual` 空数据时 `Math.max(1)` 安全、各 `map` 空数组不抛错。
- ⚠️ **需人工 F12 复核**：本环境无法起真实浏览器加载 CDN（Bootstrap/ECharts 走 jsdelivr），控制台是否干净、图表是否正常渲染，建议交付前人工过一遍。

---

## 三、三类清单（按优先级）

### 必须修复（P0，共 1 项）

| # | 问题 | 位置 | 影响 | 修复方案 |
|---|---|---|---|---|
| 1 | ECharts 图表窗口缩放后不自动 resize | `overview.js` / `form.js` / `association.js` | 浏览器窗口缩放后图表溢出/错位，最常见操作之一 | 三处统一加 `window.addEventListener('resize', () => Object.values(charts).forEach(c => c.resize()))`；`overview.js` 需先把 `echarts.init` 实例存入 `charts` 对象（当前未保存实例） |

### 建议优化（P1，不阻塞，可顺手做 2 项高价值）

| # | 问题 | 位置 | 说明 |
|---|---|---|---|
| 2 | `/api/comments` 的 `form` 未校验 | `app.py` + `analytics.py` | 非法 form 静默返回 film 数据；建议加 `_check_form` 或显式 whitelist |
| 3 | favicon 404 | `base.html` | 加 `<link rel="icon" ...>` 或空 data URI 消除 404 |
| 4 | 评论表 / 主题表无固定表头 | `form.html` / `association.html` | 当前 20 行/页价值有限，若未来调大 `limit` 则建议加 `thead { position: sticky }` |
| 5 | Overview KPI 口径混排 | `index.html` + `analytics.py` | 「总采集量(2358 含 other 89)」与「Series/Film 主样本(排除 other)」并列无说明，建议加 tooltip 或副标题 |

### 可选优化（P2，视觉/代码整洁，不做不影响交付）

| # | 问题 | 说明 |
|---|---|---|
| 6 | 标题层级微不一致（h5 vs h6） | `index.html` 卡片标题统一为 h6 或 `form.html` 升为 h5 |
| 7 | 热力图渲染代码重复 | `form.js` 与 `association.js` 的 `renderResidual` 几乎重复，可提取共用函数 |
| 8 | `overview.js` 情感图 `yAxis.max=80` 写死 | 当前最高 67.28 够用，未来数据变化可能截断 |

---

## 四、建议执行顺序

1. 修 P0 #1（resize）—— 唯一必须项。
2. 顺手修 P1 #2、#3（form 校验 + favicon，零风险高价值）。
3. 其余 P1/P2 不阻塞，可留待以后。
4. 完成后进入 README + GitHub 工程整理。

---

## 五、本轮修复记录（2026-08-21）

| # | 问题 | 状态 | 改动 |
|---|---|---|---|
| 1 | ECharts 不 resize | ✅ 已修复 | `overview.js` 新增 `charts` 缓存 + `getChart()`（原 `echarts.init` 未保存实例）；`overview.js` / `form.js` / `association.js` 三处统一加 `window.addEventListener('resize', ...)` 循环 resize |
| 2 | `/api/comments` form 未校验 | ✅ 已修复 | `app.py` 的 `api_comments` 提取 `form` 并调用 `_check_form(form)`，非法值现返回 404（实测 `form=bogus`/`BOGUS` → 404，`series`/`film` → 200） |
| 3 | favicon 404 | ✅ 已修复 | `base.html` 加 `<link rel="icon" href="data:,">` 消除 404 |

**剩余未处理**：P1 #4（固定表头）、#5（KPI 口径说明）；P2 #6/#7/#8。均不阻塞交付，可留待以后。
