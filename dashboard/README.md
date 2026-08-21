# 国产动画海外舆情看板（Dashboard）

Flask + Bootstrap + ECharts 四页 MVP。当前为 **v0：骨架 + Overview 首页**。

## 运行

```bash
cd dashboard
python app.py
```

浏览器打开 http://127.0.0.1:5000

## 依赖

- flask
- pandas（读 CSV / xlsx）
- openpyxl（pandas 读 xlsx 需要）

安装：

```bash
pip install flask pandas openpyxl
```

## 结构

- `app.py` —— 路由 + API
- `data_loader.py` —— 读封版数据（analytical_*.csv / sentiment xlsx）
- `analytics.py` —— 组织成前端 JSON（复用封版口径，不重算）
- `templates/` —— base.html + index.html
- `static/` —— css / js

## 原则

看板**不重算统计**，所有数字来自封版文件：

- `analytical_series.csv` / `analytical_film.csv` / `analytical_all.csv`
- `07_association_results.xlsx`（关联页用）
- 情感主口径 `platform_balanced` 直接读 `storage2/.../series|film_sentiment_final_summary.xlsx` 的「三口径对比」sheet

## 说明

前端图表库（Bootstrap / ECharts）当前走 CDN（jsdelivr），需要联网。
如需离线，可把对应 .js/.css 下载到 `static/` 下再改 `base.html` 的引用。
