# 数据规范（DATA_SPEC）

> 这份文档是所有爬虫输出和所有分析输入的**唯一标准**。写爬虫的人照着它出 CSV，写分析的人照着它读 CSV。有疑问先看这里，不要各自理解。

## 1. 数据分两层

### 1.1 原始层（raw）—— 爬虫直接输出

**固定 9 列**，所有平台统一。这是合并脚本 `01_merge_clean.py` 能跑通的前提。

```
page_url, anime_name, source, comment_id, author, post_time, score, crawl_time, content
```

### 1.2 分析层（analytical）—— 管线加工后

在原始 9 列基础上，`content` 拆成 `content_raw` / `content_clean`，并新增语言、情感、主题字段。当前最终产物是 `storage/05主题分析/05_topic_labeled.csv`（54 列）。

---

## 2. 原始 9 列定义

| # | 列名 | 含义 | 必填 | 示例 |
|---|------|------|------|------|
| 1 | `page_url` | 该条评论的**唯一页面链接** | ✅ | `https://myanimelist.net/reviews.php?id=596502` |
| 2 | `anime_name` | 作品英文规范名 | ✅ | `Link Click` / `RMJI` / `Ne Zha` |
| 3 | `source` | 平台名 | ✅ | `MAL` / `AniList` / `YouTube` / `X` / `RT` / `IMDb` |
| 4 | `comment_id` | 平台内唯一评论 ID | ✅ | `review:596502` |
| 5 | `author` | 评论者用户名 | ✅ | `JuicyMelons1945` |
| 6 | `post_time` | 评论发布时间（原样字符串） | ✅ | `Mar 13, 2026` |
| 7 | `score` | 平台原始评分/点赞数（**原样存，不做归一化**） | ✅ | `10` / `3` / `775` |
| 8 | `crawl_time` | 爬取时间 | ✅ | `2026-08-13 11:30:00` |
| 9 | `content` | 评论文本（完整正文，不截断） | ✅ | 见下 |

> **Reddit 例外**：历史遗留，`reddit_comments.csv` 的第 3 列叫 `subreddit` 而不是 `source`。合并脚本已做兼容处理。新写的爬虫（RT/IMDb）一律用 `source`。

### 字段细节

- **`anime_name` 取值**：只允许用下面这些规范名，不要写别名（否则合并时对不齐）。
  - **Dataset A 剧集（6 部）**：`Link Click` / `RMJI` / `Ling Cage` / `Soul Land` / `BTTH` / `Scissor Seven`
  - **Dataset B 电影（7 部）**：`Ne Zha` / `Ne Zha 2` / `White Snake` / `Jiang Ziya` / `New Gods: Nezha Reborn` / `New Gods: Yang Jian` / `I Am What I Am`
  - 新增电影（如《长安三万里》《浪浪山小妖怪》等）**先和 owner 确认命名**再填，别擅自合并进现有 `anime_name`。

- **`score` 跨平台不可比**：Reddit 是 karma、YouTube/X 是点赞数、AniList 是 0–100 评分、MAL 是 0–10 评分。**原样存**，分析时只能同平台内比较。

- **`content`**：存**完整正文**。注意有些平台正文有"折叠/展开"，要拿到展开后的完整文本（MAL 的 `.text` 容器里 `display:none` 的折叠部分也要包含）。

---

## 3. `source` 合法取值

| 值 | 平台 |
|----|------|
| `Reddit` | Reddit |
| `AniList` | AniList |
| `YouTube` | YouTube |
| `X` | X (Twitter) |
| `MAL` | MyAnimeList |
| `RT` | Rotten Tomatoes（A 负责） |
| `IMDb` | IMDb（A 负责） |

大小写、拼写必须一致（注意 `AniList` 是 L 大写，`YouTube` 是 T 大写）。

---

## 4. `comment_id` 格式

- **带前缀，避免跨平台撞 ID**：
  - MAL / AniList：`review:{id}`，如 `review:596502`
  - Reddit：`t1_{comment_id}` 或原 comment id
  - YouTube / X：直接用平台 comment id
- RT / IMDb：**照这个思路，用平台自己的唯一 ID，加一个能区分平台的前缀**（如 `rt:{id}` / `imdb:{id}`），并和 owner 确认。
- 去重依赖 `comment_id`，所以它必须**平台内唯一**。

---

## 5. 编码规范

- **CSV 一律 `utf-8-sig`**（带 BOM，Excel 打开不乱码）。
- 脚本里写 CSV：`open(..., encoding="utf-8-sig", newline="")`。
- 控制台打印中文：脚本开头 `sys.stdout.reconfigure(encoding="utf-8")`（Windows 默认 GBK 会报 `UnicodeEncodeError`）。

---

## 6. 去重规则

- `comment_id` 非空：按 `source + comment_id` 去重。
- `comment_id` 为空（如 Reddit 历史数据）：按 `source + page_url + author + post_time + 正文哈希` 兜底。
- 爬虫要支持**续跑**：读现有 CSV 的已有 `comment_id` 集合，跳过已抓的。

---

## 7. Series vs Film 数据集（2026-08-13 重构，替代原 Core/Extended）

这是 Phase 2 重构后的分层，**所有人按这个理解数据，不要混淆**：

- **Dataset A — Series（系列动画 / 连载动画）**：6 部剧集 × 5 平台（Reddit / AniList / YouTube / X / MAL）。研究问题：不同海外平台如何评价中国系列动画？
- **Dataset B — Film（动画电影）**：7 部电影 × 多平台（RT / IMDb / X / YouTube / Reddit）。研究问题：同一批中国动画电影，在不同海外社区舆情是否存在差异？

> ⚠️ 关键：**Ne Zha（2019）在 Dataset B（电影）**，Ne Zha 2（2025）也在 Dataset B。不要把两个电影合并成一个 `anime_name`。
> 数据里用 `form` 列标识：`series` / `film`。合并脚本按 `anime_name` 自动打标，爬虫不用管、也不写这一列。

---

## 8. 分析层关键字段（B 做分析要懂）

分析级数据（`05_topic_labeled.csv`）在原始 9 列之外，最重要的是这几个：

| 字段 | 含义 | 取值 |
|------|------|------|
| `record_id` | 全局唯一记录 ID | `REC00001` |
| `form` | 数据集分层（系列动画 vs 电影） | `series` / `film` |
| `content_raw` / `content_clean` | 原始 / 清洗后的正文 | 文本 |
| `lang` / `lang_group` | 语言（启发式 / langdetect 细分） | `en` / `zh` / `id` / `ja` / `unknown` ... |
| `is_relevant` | 是否相关（噪音过滤标记） | True/False |
| `sentiment_final` | **最终情感（分析用这个，别用 sentiment_pred）** | `positive` / `neutral` / `negative` / `mixed` / `other` |
| `sentiment_score` | 情感得分（pos−neg） | 浮点 |
| `topic_story_plot` ... `topic_ip_derivative` | 12 个主题布尔列 | True/False |
| `topic_list` | 命中的主题列表 | `剧情;画面动画` |
| `topic_count` | 命中主题数 | 整数 |

- **情感统一用 `sentiment_final`**：这是"模型预测 + 人工复核"后的最终结果。`sentiment_pred` 是模型原始预测（会高估负面），不要直接拿来做结论。
- **统计基数**：算情感/主题占比时，通常**排除 `other`**（非明确情感），口径要和 owner 对齐。

---

## 9. 踩过的坑（写代码前先看，别重踩）

1. **MAL 改版**：评论容器是 `.review-element.js-review-element`（不是网上的旧教程写的 `.borderDark`）。
2. **MAL URL 要带 slug**：`/anime/{id}/{slug}/reviews` 才有完整列表，不带 slug 只有 3 条缩略。
3. **MAL 分页越界回退**：`?p=` 超过最后一页会回退到第 1 页，翻页结束要**靠去重判断**，不能只看页数。
4. **代理**：`googleapis.com`、`api.x.com`、MAL 都要走 Clash `127.0.0.1:7890`，超时设大（≥40s）。
5. **反爬**：Reddit 是 IP 级封锁（目前靠日本节点 + stealth 才通），新平台先探针验证，别假设能直接 requests 通。
6. **编码**：CSV 用 `utf-8-sig`，控制台用 `sys.stdout.reconfigure`。
