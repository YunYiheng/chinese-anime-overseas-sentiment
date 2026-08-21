"""
RT（Rotten Tomatoes）爬虫模板 —— 实习生 A 使用

============================================================
【必读】写之前先看 docs/DATA_SPEC.md，输出必须遵守 9 列规范。
============================================================

这个模板给了你两个阶段：
  1. 探针（rt_probe）：先搞清楚 RT 能不能 requests 直连、字段在哪、分页怎么翻。
  2. 正式爬虫（rt_crawler）：探针确认可行后再写，输出 rt_data.csv（9 列）。

参考已完成且验证过的同类爬虫：根目录 mal_crawler.py（MAL，requests 直连版）。
如果探针发现 RT 需要 JS 渲染，再看 storage/爬虫与原始数据/ 下的 Playwright 爬虫做参考。

【统一约定】
  - CSV 编码 utf-8-sig（Excel 不乱码）
  - 脚本开头 sys.stdout.reconfigure(encoding="utf-8")
  - 输出 9 列：page_url, anime_name, source, comment_id, author, post_time, score, crawl_time, content
  - source 写 "RT"；comment_id 加前缀（如 rt:{平台id}），保证平台内唯一
  - 支持限速(time.sleep) + 失败重试 + 按 comment_id 去重续跑
"""
import sys
import os
import time
import csv
import json
from datetime import datetime

import requests
from bs4 import BeautifulSoup

# ============================================================
# 0. 基础配置
# ============================================================
OUTPUT_CSV = "rt_data.csv"
FIELDNAMES = ["page_url", "anime_name", "source", "comment_id",
              "author", "post_time", "score", "crawl_time", "content"]

REQUEST_TIMEOUT = 40
SLEEP_BETWEEN = 1.2  # 温和限速，别打满

# 读取 Clash 代理（.env 的 CLASH_PROXY=）
PROXY = None
try:
    with open(".env", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("CLASH_PROXY="):
                PROXY = line.split("=", 1)[1]
except FileNotFoundError:
    pass
PROXIES = {"http": PROXY, "https": PROXY} if PROXY else None

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/149.0.0.0 Safari/537.36"
}

session = requests.Session()
session.headers.update(HEADERS)


# ============================================================
# 1. 探针阶段（先跑这个，确认可行再写正式爬虫）
# ============================================================
# ============================================================
# 已由 owner 探针验证过的 RT 电影 URL（2026-08-13，7 部已确认可直连）
#   —— 这些 URL 经 requests + Clash 代理实测 HTTP 200，直接用。
# 其余 2 部（长安三万里 / 浪浪山小妖怪）slug 未确认，需你自己在 RT 站内搜。
# 【重要结论】RT 评论是服务端渲染（嵌在 data-json="reviewsData" 的 JSON 里），
#   requests 直连即可，不需要 Playwright。详见 docs/rt_probe_findings.md。
# ============================================================
PROBE_TARGETS = [
    {"anime_name": "Ne Zha", "rt_url": "https://www.rottentomatoes.com/m/ne_zha"},
    {"anime_name": "Ne Zha 2", "rt_url": "https://www.rottentomatoes.com/m/ne_zha_ii"},
    {"anime_name": "White Snake", "rt_url": "https://www.rottentomatoes.com/m/white_snake"},
    {"anime_name": "Jiang Ziya", "rt_url": "https://www.rottentomatoes.com/m/jiang_ziya"},
    {"anime_name": "New Gods: Nezha Reborn", "rt_url": "https://www.rottentomatoes.com/m/new_gods_nezha_reborn"},
    {"anime_name": "New Gods: Yang Jian", "rt_url": "https://www.rottentomatoes.com/m/new_gods_yang_jian"},
    {"anime_name": "I Am What I Am", "rt_url": "https://www.rottentomatoes.com/m/i_am_what_i_am"},
]


def fetch(url, retries=4):
    """GET 一个 URL，带重试。返回 HTML 文本或 None。"""
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=REQUEST_TIMEOUT, proxies=PROXIES)
            if r.status_code == 200:
                return r.text
            print(f"    [status={r.status_code}] 重试 {attempt+1}...")
            time.sleep(3 * (attempt + 1))
        except requests.RequestException as e:
            print(f"    [网络错误] {e}")
            time.sleep(3 * (attempt + 1))
    return None


def probe_one(work_name, rt_url):
    """
    探针一个 RT 电影页面，回答下面 5 个问题并打印。
    【TODO】根据实际页面结构，把「待确认」改成真实的选择器/结论。
    """
    print(f"\n===== 探针：{work_name} =====")
    html = fetch(rt_url)
    if html is None:
        print("  [失败] 拿不到页面（可能被反爬或需要 JS）")
        return

    soup = BeautifulSoup(html, "lxml")

    # 问题 1：评论是服务器端渲染，还是 JS 动态加载？
    # 判断方法：HTML 里搜评论容器/关键词，看有没有。
    # 【TODO】找 RT 观众评论的容器选择器，例如 soup.select("...")
    # 如果 requests 拿到的 HTML 里没有评论 → 需要 Playwright。

    # 问题 2：评论字段（作者/时间/评分/正文）分别在哪？
    # 【TODO】对照 DATA_SPEC 的 9 列，逐一填选择器。

    # 问题 3：分页方式？URL 参数还是"加载更多"按钮？
    # 【TODO】找到翻页入口，判断是 ?page=N 还是按钮。

    # 问题 4：有没有反爬（Cloudflare / 验证码 / 429）？
    # 【TODO】多测几次，记录状态码和拦截页特征。

    # 问题 5：总评论量大概多少？
    # 【TODO】找到"XX reviews"总数。

    print("  （以上 TODO 由你根据实际页面填写）")


def run_probe():
    for t in PROBE_TARGETS:
        probe_one(t["anime_name"], t["rt_url"])
        time.sleep(SLEEP_BETWEEN)
    # 探针结论输出到一个 md：rt_probe_report.md
    print("\n探针完成，把结论写进 rt_probe_report.md 再进入正式爬虫。")


# ============================================================
# 2. 正式爬虫阶段（探针确认后填）
# ============================================================
def parse_review(el, anime_name):
    """
    从单个评论容器提取字段，返回一个 9 列 dict。
    【TODO】把下面每个 TODO 换成探针验证过的真实选择器。
    """
    # 评论唯一 ID + 页面链接
    rid = ""  # 【TODO】提取平台评论 id
    if not rid:
        return None
    comment_id = f"rt:{rid}"
    page_url = f"https://www.rottentomatoes.com/..."  # 【TODO】评论页链接

    author = ""       # 【TODO】评论者
    post_time = ""    # 【TODO】发布时间
    score = ""        # 【TODO】评分（原样）
    content = ""      # 【TODO】正文（完整）

    return {
        "page_url": page_url,
        "anime_name": anime_name,
        "source": "RT",
        "comment_id": comment_id,
        "author": author,
        "post_time": post_time,
        "score": score,
        "crawl_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "content": content,
    }


def load_existing_ids():
    """读现有 rt_data.csv 的 comment_id，用于续跑去重。"""
    existing = set()
    if os.path.exists(OUTPUT_CSV):
        with open(OUTPUT_CSV, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row.get("comment_id"):
                    existing.add(row["comment_id"])
    return existing


def crawl():
    """正式爬取主流程。"""
    existing = load_existing_ids()
    rows = []

    # 【TODO】遍历作品 × 翻页，解析评论，跳过已有 comment_id
    # 参考 mal_crawler.py 的 crawl_work()：翻页 + 去重 + 结束判断。

    # 追加写入（保留已有 + 新增）
    write_header = not os.path.exists(OUTPUT_CSV)
    with open(OUTPUT_CSV, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()
        for r in rows:
            writer.writerow(r)
    print(f"完成，新增 {len(rows)} 条 → {OUTPUT_CSV}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    # 先跑探针：python rt_crawler_template.py --probe
    # 探针确认后跑正式：python rt_crawler_template.py --crawl
    if "--probe" in sys.argv:
        run_probe()
    else:
        crawl()
