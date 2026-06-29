#!/usr/bin/env python3
"""每日新闻速览 - 抓取 RSS 新闻并推送到微信 (ServerChan)"""

import os
import re
import sys
import time
import logging
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import feedparser
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ── RSS 源配置（按领域分组）────────────────────────────────────────────
RSS_SOURCES = {
    "🌍 时政·国际": [
        ("联合早报", "https://www.zaobao.com/recent.rss"),
        ("BBC中文", "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml"),
        ("Reuters", "https://www.reutersagency.com/feed/"),
    ],
    "💻 科技": [
        ("Hacker News", "https://hnrss.org/frontpage?count=20"),
        ("少数派", "https://sspai.com/feed"),
        ("ArsTechnica", "https://feeds.arstechnica.com/arstechnica/index"),
    ],
    "📈 财经·商业": [
        ("36氪", "https://36kr.com/feed"),
        ("TechCrunch", "https://techcrunch.com/feed/"),
        ("华尔街见闻", "https://wallstreetcn.com/rss"),
    ],
    "🏘️ 社会·民生": [
        ("知乎日报", "https://daily.zhihu.com/rss"),
        ("The Guardian", "https://www.theguardian.com/world/rss"),
    ],
    "🔬 科学·健康": [
        ("果壳网", "https://www.guokr.com/rss.xml"),
        ("Nature", "https://www.nature.com/nature.rss"),
    ],
}

SENDKEY = os.environ.get("SENDKEY", "")
if not SENDKEY:
    log.error("环境变量 SENDKEY 未设置")
    sys.exit(1)

SERVERCHAN_URL = f"https://sctapi.ftqq.com/{SENDKEY}.send"

TZ_CST = timezone(timedelta(hours=8))


# ── 工具函数 ───────────────────────────────────────────────────────────

def fetch_feed(url, timeout=15):
    """抓取并解析 RSS 源，失败返回空列表"""
    try:
        feed = feedparser.parse(url)
        if feed.bozo and not feed.entries:
            log.warning("解析失败 (bozo): %s", url)
            return []
        log.info("  ✓ %s → %d 条", url, len(feed.entries))
        return feed.entries
    except Exception as e:
        log.warning("  ✗ %s → %s", url, e)
        return []


def safe_str(text):
    """清理文本中的非法字符"""
    if not text:
        return ""
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(text))
    return text.strip()


def extract_pubdate(entry):
    """统一解析发布日期"""
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return datetime.now(timezone.utc)


def truncate(text, max_len=80):
    """截断长文本"""
    if len(text) > max_len:
        return text[:max_len].rstrip() + "…"
    return text


# ── 核心逻辑 ───────────────────────────────────────────────────────────

def collect_news():
    """从所有 RSS 源抓取新闻，按领域和来源分类"""
    all_news = []  # [(category_label, source_name, title, url, summary, pubdate)]
    for category, sources in RSS_SOURCES.items():
        for name, url in sources:
            entries = fetch_feed(url)
            for entry in entries:
                title = safe_str(entry.get("title", ""))
                if not title:
                    continue
                link = entry.get("link", "")
                summary = safe_str(entry.get("summary", "") or entry.get("description", ""))
                summary = summary[:200]
                pubdate = extract_pubdate(entry)
                all_news.append((category, name, title, link, summary, pubdate))
    return all_news


def deduplicate(news_list):
    """基于标题前 20 字去重"""
    seen = set()
    result = []
    for item in news_list:
        key = item[2][:20].lower().strip()
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result


def select_top(news_list, n=20):
    """从各领域轮询选取 n 条最重要的新闻"""
    # 按领域分组
    by_category = defaultdict(list)
    for item in news_list:
        by_category[item[0]].append(item)

    # 各组内按时间排序（最新的靠前）
    for cat in by_category:
        by_category[cat].sort(key=lambda x: x[5], reverse=True)

    # 轮询选取, 优先从每个分类取，保证覆盖面
    selected = []
    categories = list(by_category.keys())
    # 按领域条目数从多到少排序（避免小领域被饿死）
    categories.sort(key=lambda c: len(by_category[c]), reverse=True)

    # 先给每个分类至少 1 条
    queue = list(categories)
    while queue and len(selected) < n:
        cat = queue.pop(0)
        if by_category[cat]:
            selected.append(by_category[cat].pop(0))
            if by_category[cat]:
                queue.append(cat)

    return selected[:n]


def format_digest(news_items):
    """格式化为 ServerChan 的 Markdown 消息体"""
    today_cn = datetime.now(TZ_CST).strftime("%Y年%m月%d日")
    today_short = datetime.now(TZ_CST).strftime("%Y-%m-%d")

    lines = []
    lines.append(f"📰 **每日新闻速览 · {today_cn}**")
    lines.append("")

    for i, (cat, source, title, link, summary, _pub) in enumerate(news_items, 1):
        short_summary = truncate(summary, 80) if summary else truncate(title, 60)
        lines.append(f"{i}. {cat} [{source}] **{title}**")
        lines.append(f"   > {short_summary}")
        if link:
            lines.append(f"   [阅读原文]({link})")
        lines.append("")

    lines.append("---")
    lines.append("")
    # 今日焦点：取第一条
    top = news_items[0]
    lines.append(f"📌 **今日焦点**：{top[2]}")
    lines.append("")
    lines.append(f"🕐 推送时间：{datetime.now(TZ_CST).strftime('%H:%M')}")
    lines.append("")

    return "\n".join(lines)


def push_to_wechat(title, content):
    """通过 ServerChan 推送到微信"""
    resp = requests.post(
        SERVERCHAN_URL,
        data={"title": title, "desp": content},
        timeout=20,
    )
    result = resp.json()
    if result.get("code") == 0:
        log.info("推送成功: %s", result.get("data", {}).get("pushid", ""))
        return True
    else:
        log.error("推送失败: %s", result.get("message", "未知错误"))
        return False


# ── 主流程 ─────────────────────────────────────────────────────────────

def main():
    start = time.time()
    log.info("=" * 50)
    log.info("开始抓取新闻…")

    today_short = datetime.now(TZ_CST).strftime("%Y-%m-%d")

    all_news = collect_news()
    log.info("共抓取 %d 条原始新闻", len(all_news))

    all_news = deduplicate(all_news)
    log.info("去重后 %d 条", len(all_news))

    top_news = select_top(all_news, n=20)
    log.info("精选 %d 条", len(top_news))

    content = format_digest(top_news)
    title = f"📰 每日新闻速览 · {today_short}"

    # 也保存本地一份
    output_path = os.path.join(os.path.dirname(__file__) or ".", f"{today_short}.md")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    log.info("已保存到 %s", output_path)

    success = push_to_wechat(title, content)
    elapsed = time.time() - start
    log.info("耗时 %.1f 秒", elapsed)

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()

