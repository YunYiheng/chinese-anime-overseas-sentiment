# 国产动漫海外舆情分析项目

采集海外网民对国产动漫及 IP 的评价，完成情感分析、主题标注与关联分析，产出最终分析报告与 Flask 数据看板。

## 最终成果

| 交付物 | 说明 |
|--------|------|
| `国产动画海外舆情分析报告.docx` | 最终报告（8 章 + 2 附录，含目录、图表、30 条代表评论卡片） |
| `dashboard/` | Flask 四页数据看板（Overview / Series / Film / Association） |
| `analytical_series.csv` / `analytical_film.csv` / `analytical_all.csv` | 最终 3 张封版分析表 |
| `07_association_results.xlsx` | 关联分析结果（χ² / Cramér's V / 标准化残差 / Bonferroni 校正） |

## 数据规模

- 总采集 **2358 条**（含 `other` 89 条：series 16 + film 73）
- **Series 层**：6 部连载动画 × 5 平台 = 1233 条（主样本 1217，排除 other）
- **Film 层**：7 部动画电影 × 多平台 = 1125 条（主样本 1052，排除 other）
- 共 **6 个平台**：Reddit / AniList / YouTube / X / MAL / Rotten Tomatoes

> Series/Film 两层拆分是研究设计的关键：剧集观众与电影观众的评论习惯、平台分布存在系统性差异（YouTube 上电影集中在预告/片段/影评，剧集集中在正片/打斗/OP），拆开后「作品形态」这个隐藏变量被控制，研究更干净。

## 数据集结构（Series / Film 两层）

**Dataset A — Series 系列动画**（6 部 × 5 平台）：

| 作品 | 英文名 |
|------|--------|
| 时光代理人 | Link Click |
| 凡人修仙传 | RMJI (A Record of a Mortal's Journey) |
| 灵笼 | Ling Cage |
| 斗罗大陆 | Soul Land |
| 斗破苍穹 | Battle Through the Heavens (BTTH) |
| 刺客伍六七 | Scissor Seven |

**Dataset B — Film 动画电影**（7 部 × RT/X/YouTube 等）：

Ne Zha（2019）/ Ne Zha 2（2025）/ 白蛇：缘起 / 姜子牙 / 新神榜：哪吒重生 / 新神榜：杨戬 / 雄狮少年（I Am What I Am）

## 数据口径（重要）

- **情感主口径 = `platform_balanced`**（准入平台等权），Series 准入 4 平台（YouTube/X/MAL/Reddit）、Film 准入 3 平台（YouTube/X/RT）。结果：Series 正面 63.5% / 中性 29.4% / 混合 2.7% / 负面 4.4%；Film 正面 67.3% / 中性 25.7% / 混合 3.7% / 负面 3.4%。
- `pooled`（全部评论汇总）为附注口径，`all_platform_equal` 仅作敏感性分析，**不进入正文**。
- 统计分母一律**排除 `other`**（无关/引战/噪音评论，共 89 条），`other` 单独审计。
- `score` 是**可缺失浮点**，各平台原始量表不可直接比较：Reddit 是 karma、YouTube/X 是点赞、MAL 0–10、AniList 0–100、RT 0.5–5 星。

## 目录结构

```
新建文件夹/
├── README.md
├── .env / .env.example / .gitignore        # .env 含密钥，gitignore 已排除
├── analytical_*.csv                        # 最终 3 张封版分析表
├── 07_association_results.xlsx             # 关联分析封版结果
├── 国产动画海外舆情分析报告.docx            # 最终报告
├── 06_freeze_analytical.py                 # 数据封版（Series/Film 拆分 + global_record_id）
├── 07_association_analysis.py              # 关联分析（χ²/Cramér's V/残差）
├── 08_generate_report_charts.py            # 报告图表
├── report_build_v2.py                      # python-docx 生成报告
├── dashboard/                              # Flask 四页看板（app.py + analytics.py + data_loader.py）
├── docs/                                   # DATA_SPEC.md 数据规范 + RT 探针结论
├── storage/                                # Phase 1 归档（4 个旧爬虫 + 原始 CSV）
│   └── 爬虫与原始数据/
└── storage2/                               # Phase 2（电影爬虫 + Series/Film 管线）
    ├── series_pipeline/                    # Series 管线 + series_sentiment_final_summary.xlsx
    ├── film_pipeline/                      # Film 管线 + film_sentiment_final_summary.xlsx
    └── *_film_crawler.py / *_film_data.csv # 电影爬虫 + 原始数据
```

> 中间产物（01–05 管线的中间 CSV、人工复核表、EDA 图表、日志）由脚本可重生成，已通过 `.gitignore` 排除，不进入版本库。

## 快速开始

### 运行 Dashboard

```bash
cd dashboard
pip install flask pandas openpyxl
python app.py
```

浏览器打开 http://127.0.0.1:5000

看板**只读封版文件、不重算统计**，所有数字与报告一致。依赖的封版文件：

- `analytical_series.csv` / `analytical_film.csv` / `analytical_all.csv`
- `07_association_results.xlsx`
- `storage2/series_pipeline/series_sentiment_final_summary.xlsx`
- `storage2/film_pipeline/film_sentiment_final_summary.xlsx`

### 复现分析管线（可选）

1. 原始数据已就位：Phase 1 五平台 CSV（`reddit_comments.csv` / `anilist_data.csv` / `youtube_data.csv` / `x_data.csv` / `mal_data.csv`）+ Phase 2 电影 CSV（`storage2/*_film_data.csv` / `rt_film_data.csv`）。
2. Series 管线：`storage2/series_pipeline/`（00 拆分 → 04 情感回填 → 05 主题）。
3. Film 管线：`storage2/film_pipeline/`（01 合并 → 02b 语言 → 03 情感 → 03a 复核 → 04 回填 → 05 主题）。
4. 数据封版：`06_freeze_analytical.py` → 3 张 analytical 表。
5. 关联分析：`07_association_analysis.py` → xlsx。
6. 报告：`08_generate_report_charts.py` + `report_build_v2.py` → docx。

## 分析管线（方法）

```
原始 9 列 CSV（各平台）
  ↓ 01 合并清洗（去重、去噪、语言启发式）
  ↓ 02 EDA / 02b 语言细分（langdetect + 中文兜底）
  ↓ 03 情感基线（多语言 XLM-R 模型）
  ↓ 03a 人工复核抽样（必审 + 分层抽样）
  ↓ 04 情感回填（manual 优先，否则 pred）
  ↓ 05 主题标注（关键词多标签，12 主题）
  ↓ 06 数据封版（Series/Film 拆分 + 三口径）
  ↓ 07 关联分析（χ² / Cramér's V / 标准化残差 / Bonferroni）
  ↓ 08 图表 + report_build → 最终报告
```

## 密钥安全

`.env` 含真实密钥（YouTube API Key、X Bearer Token、Clash 代理），`storage/爬虫与原始数据/X API.txt` 含 X Token 原文——**两者均已加入 `.gitignore`，绝不提交**。`.env.example` 是占位符模板，可安全提交。

## 环境说明

- Python 3.12，Windows 11 中文环境。
- 依赖：`requests` `bs4` `pandas` `matplotlib` `seaborn` `langdetect` `openpyxl` `flask`（情感管线另需 `torch` `transformers`）。
- 网络：`googleapis.com`、`api.x.com`、MAL 等域名需走 Clash 代理（`127.0.0.1:7890`），代理地址在 `.env` 的 `CLASH_PROXY=`。
- Windows 控制台默认 GBK，脚本开头需 `sys.stdout.reconfigure(encoding="utf-8")`。
