"""
MAL Web Probe v1 —— Playwright 诊断探针
只测 3 个典型页面，每部只开 Reviews 第一页，不翻页。
输出：CSV + debug/ 下的 HTML + PNG
"""
import sys, os, time, csv
from pathlib import Path

# === 配置 ===
MAL_REVIEW_URL = "https://myanimelist.net/anime/{mal_id}/reviews"

TARGETS = [
    {"work_key": "Link Click", "mal_id": 44074, "label": "普通热门ONA"},
    {"work_key": "RMJI",       "mal_id": 41219, "label": "国产长篇动画"},
    {"work_key": "Ne Zha",     "mal_id": 40111, "label": "电影(Movie)"},
]

DEBUG_DIR = Path("debug")
WAIT_SECONDS = 4  # 页面加载等待时间

# 读取代理（可选）
PROXY = None
try:
    with open(".env", encoding="utf-8") as f:
        for line in f:
            if line.strip().startswith("CLASH_PROXY="):
                PROXY = line.strip().split("=", 1)[1]
except FileNotFoundError:
    pass

# === 初始化 ===
def setup():
    os.makedirs(DEBUG_DIR, exist_ok=True)

    # 如果当前没有 stdout reconfigure 就做一个
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    # 动态导入 Playwright
    from playwright.sync_api import sync_playwright
    return sync_playwright()


def save_debug(page, slug):
    """保存当前页面的 HTML 和截图到 debug/"""
    html_path = DEBUG_DIR / f"{slug}.html"
    png_path = DEBUG_DIR / f"{slug}.png"

    html_path.write_text(page.content(), encoding="utf-8")
    print(f"  [debug] HTML 已保存 → {html_path}")

    page.screenshot(path=str(png_path), full_page=False)
    print(f"  [debug] 截图已保存 → {png_path}")


def parse_reviews(page):
    """
    从 MAL Reviews 页面提取评论列表。
    MAL 会动态改版，因此使用多套选择器兜底。
    返回 list[dict]
    """
    reviews = []

    # ---- 策略 A：新版 MAL 结构 ----
    # 每条评论通常在一个 borderDark 容器里
    containers = page.query_selector_all(".borderDark")
    if containers:
        print(f"  [parse] 策略A 找到 {len(containers)} 个 .borderDark 容器")
    else:
        # ---- 策略 B：备选容器 ----
        for sel in [".review-container", ".review-element", "[class*='review']"]:
            containers = page.query_selector_all(sel)
            if containers:
                print(f"  [parse] 策略B 找到 {len(containers)} 个 {sel}")
                break

    if not containers:
        # 最后一招：直接从 body 文本判断
        body_text = page.inner_text("body")
        print(f"  [parse] 未找到评论容器，页面正文前 500 字符：")
        print(f"  {body_text[:500]}")
        return reviews

    # 遍历每个容器，提取字段
    for i, c in enumerate(containers):
        try:
            review = extract_review_fields(c, page)
            if review:
                reviews.append(review)
        except Exception as e:
            print(f"  [parse] 容器 #{i} 解析异常：{e}")

    return reviews


def extract_review_fields(container, page):
    """从单个评论容器中提取字段（多选择器兜底）"""
    from playwright.sync_api import TimeoutError as PwTimeout

    # -- 评论标签：Recommended / Mixed Feelings / Not Recommended --
    label = ""
    for sel in [
        "[class*='label']",
        "[class*='recommend']",
        "span[class*='text']",
        ".review-status",
    ]:
        try:
            el = container.query_selector(sel)
            if el:
                txt = el.inner_text().strip()
                if txt and any(kw in txt.lower() for kw in ["recommend", "mixed", "not"]):
                    label = txt
                    break
        except Exception:
            continue

    # -- 评分 --
    score = ""
    for sel in [
        "[class*='rating'] span",
        "[class*='score']",
        "span:has-text('Overall')",
    ]:
        try:
            el = container.query_selector(sel)
            if el:
                txt = el.inner_text().strip()
                if txt:
                    score = txt
                    break
        except Exception:
            continue

    # -- 是否含剧透 --
    spoiler_flag = ""
    for sel in [
        "[class*='spoiler']",
        "span:has-text('spoiler')",
        "span:has-text('Spoiler')",
    ]:
        try:
            el = container.query_selector(sel)
            if el:
                spoiler_flag = "True"
                break
        except Exception:
            continue

    # -- 有用数 / reaction --
    helpful_count = ""
    for sel in [
        "[class*='helpful']",
        "span:has-text('helpful')",
        "span:has-text('people found')",
    ]:
        try:
            el = container.query_selector(sel)
            if el:
                helpful_count = el.inner_text().strip()
                break
        except Exception:
            continue

    # -- 评论者（精确选择器：.username a）--
    reviewer = ""
    try:
        el = container.query_selector(".username a")
        if el:
            reviewer = el.inner_text().strip()
    except Exception:
        pass

    # -- 评论日期（精确选择器：.update_at）--
    review_date = ""
    try:
        el = container.query_selector(".update_at")
        if el:
            review_date = el.inner_text().strip()
    except Exception:
        pass

    # -- 评分（rating .num，可能被 display:none 隐藏，用 textContent 兜底）--
    if not score:
        try:
            el = container.query_selector(".rating .num")
            if el:
                score = el.text_content().strip() or el.inner_text().strip()
        except Exception:
            pass

    # -- 有用数 / reaction 总数（从 data-reactions 属性解析） --
    if not helpful_count:
        try:
            reactions_raw = container.get_attribute("data-reactions")
            if reactions_raw:
                import json
                reactions = json.loads(reactions_raw)
                helpful_count = str(reactions.get("num", ""))
        except Exception:
            pass

    # -- 评论文本（精确选择器：.text）--
    review_text = ""
    try:
        el = container.query_selector(".text")
        if el:
            # textContent 可以拿到被 "..." 折叠隐藏的内容
            review_text = el.text_content().strip()[:3000]
    except Exception:
        pass

    # 兜底
    if not review_text:
        review_text = container.inner_text().strip()[:3000]

    # 跳过明显不是评论的容器
    if not reviewer and not label and len(review_text) < 10:
        return None

    return {
        "reviewer": reviewer,
        "review_date": review_date,
        "review_text": review_text,
        "review_label": label,
        "review_score": score,
        "spoiler_flag": spoiler_flag,
        "helpful_count": helpful_count,
    }


def probe_one_page(playwright, target):
    """探测一个 MAL 页面，返回结果行列表"""
    work_key = target["work_key"]
    mal_id = target["mal_id"]
    page_url = MAL_REVIEW_URL.format(mal_id=mal_id)
    slug = work_key.replace(" ", "_").lower()

    print(f"\n{'='*60}")
    print(f"目标：{work_key} (MAL ID={mal_id}) - {target['label']}")
    print(f"URL：{page_url}")
    print(f"{'='*60}")

    result_rows = []
    page_status = "unknown"

    # 启动浏览器（有头模式，亲眼确认）
    browser = playwright.chromium.launch(headless=False)
    context_kwargs = {}
    if PROXY:
        context_kwargs["proxy"] = {"server": PROXY}
    context = browser.new_context(**context_kwargs)
    page = context.new_page()

    try:
        # 打开页面
        print(f"  正在打开页面...")
        try:
            page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
            page_status = f"HTTP {page.evaluate('document.readyState')}"
        except Exception as e:
            page_status = f"GOTO_FAILED: {e}"
            print(f"  [ERROR] 页面加载失败：{e}")
            save_debug(page, f"{slug}_load_fail")
            return result_rows

        # 等待内容渲染
        print(f"  等待 {WAIT_SECONDS}s 让内容渲染...")
        time.sleep(WAIT_SECONDS)

        # 保存调试文件
        save_debug(page, slug)

        # 检查页面状态
        current_url = page.url
        print(f"  当前 URL：{current_url}")

        # 检测 Cloudflare 等拦截
        body_text = page.inner_text("body")[:1000]
        if "cloudflare" in body_text.lower() or "verify you are human" in body_text.lower():
            page_status = "BLOCKED: Cloudflare or captcha detected"
            print(f"  [WARN] {page_status}")

        # 解析评论
        reviews = parse_reviews(page)
        print(f"  提取到 {len(reviews)} 条评论")

        # 构造输出行
        for r in reviews:
            row = {
                "work_key": work_key,
                "mal_id": mal_id,
                "page_url": page_url,
                "page_status": page_status,
                "review_count_on_page": len(reviews),
                "reviewer": r["reviewer"],
                "review_date": r["review_date"],
                "review_text": r["review_text"],
                "review_label": r["review_label"],
                "review_score": r["review_score"],
                "spoiler_flag": r["spoiler_flag"],
                "helpful_count": r["helpful_count"],
            }
            result_rows.append(row)

        # 即使没评论也要有一行概要
        if not result_rows:
            result_rows.append({
                "work_key": work_key,
                "mal_id": mal_id,
                "page_url": page_url,
                "page_status": page_status,
                "review_count_on_page": 0,
                "reviewer": "",
                "review_date": "",
                "review_text": "",
                "review_label": "",
                "review_score": "",
                "spoiler_flag": "",
                "helpful_count": "",
            })

    except Exception as e:
        print(f"  [FATAL] {e}")
        page_status = f"FATAL: {e}"
        try:
            save_debug(page, f"{slug}_fatal")
        except Exception:
            pass
        result_rows.append({
            "work_key": work_key, "mal_id": mal_id, "page_url": page_url,
            "page_status": page_status, "review_count_on_page": 0,
            "reviewer": "", "review_date": "", "review_text": "",
            "review_label": "", "review_score": "", "spoiler_flag": "", "helpful_count": "",
        })

    finally:
        browser.close()

    return result_rows


def main():
    from playwright.sync_api import sync_playwright

    os.makedirs(DEBUG_DIR, exist_ok=True)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    with sync_playwright() as pw:
        all_rows = []
        for target in TARGETS:
            rows = probe_one_page(pw, target)
            all_rows.extend(rows)
            time.sleep(2)

    # 写入 CSV
    csv_path = "mal_probe_reviews.csv"
    fieldnames = [
        "work_key", "mal_id", "page_url", "page_status",
        "review_count_on_page", "reviewer", "review_date",
        "review_text", "review_label", "review_score",
        "spoiler_flag", "helpful_count",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\n{'='*60}")
    print(f"探针完成！")
    print(f"  CSV  → {csv_path} ({len(all_rows)} 行)")
    print(f"  HTML/PNG → {DEBUG_DIR}/")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
