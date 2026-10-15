import os
import re
import sys
import traceback
from collections import Counter, defaultdict
from datetime import datetime

import requests
from openai import OpenAI

# 并发抓取 / 去重 / 渲染 / 发送等通用能力见 scripts/digest_common.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import digest_common as digest  # noqa: E402

# ---------------------------------------------------------------------------
# 读取环境变量
# ---------------------------------------------------------------------------
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL") or "deepseek-flash"
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.gmail.com")

try:
    EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "465"))
except ValueError:
    EMAIL_PORT = 465

EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER", "")

# ---------------------------------------------------------------------------
# Flow 元信息
# ---------------------------------------------------------------------------
FLOW_NAME = "companywatch"
SUBJECT = "【CompanyWatch】本周高曝光科技公司盘点"
BRAND_TITLE = "🏢 CompanyWatch · 本周高曝光科技公司盘点"
SUBTITLE = "半导体 / AI 芯片 / LLM 公司动态，国内 + 国外"
FOOTER = ""
BACKUP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")

# ---------------------------------------------------------------------------
# 1. 数据源：全球科技 + 半导体/AI 芯片专业媒体 + 国内科技媒体
# ---------------------------------------------------------------------------
CATEGORY_MAX_ITEMS = {
    "Tech_News": 5,
    "Chip_News": 6,
}

MODULE_FEEDS = {
    "Tech_News": {
        "The Verge": "https://www.theverge.com/rss/index.xml",
        "TechCrunch": "https://techcrunch.com/feed/",
        "Ars Technica": "https://feeds.arstechnica.com/arstechnica/index",
        "Wired": "https://www.wired.com/feed/rss",
        "BBC Tech": "https://feeds.bbci.co.uk/news/technology/rss.xml",
        "MIT Technology Review": "https://www.technologyreview.com/feed/",
        "The Next Web": "https://thenextweb.com/feed",
        "The Register": "https://www.theregister.com/headlines.atom",
        "Hacker News": "https://hnrss.org/frontpage",
        "IT之家": "https://www.ithome.com/rss/",
        "爱范儿": "https://www.ifanr.com/feed",
        "极客公园": "https://www.geekpark.net/rss",
        "钛媒体": "https://www.tmtpost.com/rss.xml",
        "量子位": "https://www.qbitai.com/feed",
        "雷峰网": "https://www.leiphone.com/feed",
        "Solidot": "https://www.solidot.org/index.rss",
        "少数派": "https://sspai.com/feed",
        "OSCHINA": "https://www.oschina.net/news/rss",
    },
    "Chip_News": {
        "SemiEngineering": "https://semiengineering.com/feed/",
        "EE Times": "https://www.eetimes.com/feed/",
        "IEEE Spectrum Semiconductors": "https://spectrum.ieee.org/feeds/topic/semiconductors.rss",
        "The Next Platform": "https://www.nextplatform.com/feed/",
        "Tom's Hardware": "https://www.tomshardware.com/feeds/all",
        "TechPowerUp": "https://www.techpowerup.com/rss/news",
        "Chips and Cheese": "https://chipsandcheese.com/feed/",
    },
}

JSON_FEEDS = {
    "Tech_News": [
        {
            "name": "新浪科技滚动",
            "type": "sina_roll",
            "url": "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2509&num=30",
        },
        {
            "name": "36氪热榜",
            "type": "36kr_hot",
            "url": "https://gateway.36kr.com/api/mis/nav/home/nav/rank/hot",
        },
    ],
}

# ---------------------------------------------------------------------------
# 2. 公司观察清单。曝光度 = 本周抓取条目中提及该公司的条目数。
#    聚焦半导体、AI 芯片、LLM 公司，覆盖国内与国外。
# ---------------------------------------------------------------------------
COMPANY_WATCHLIST = [
    # 国外：AI 芯片 / GPU / 半导体
    {"name": "NVIDIA", "aliases": ["nvidia", "英伟达"], "field": "AI芯片/GPU", "region": "国外"},
    {"name": "TSMC", "aliases": ["tsmc", "台积电"], "field": "半导体制造", "region": "国外"},
    {"name": "Intel", "aliases": ["intel", "英特尔"], "field": "半导体", "region": "国外"},
    {"name": "AMD", "aliases": ["amd"], "field": "AI芯片/CPU", "region": "国外"},
    {"name": "Samsung", "aliases": ["samsung", "三星"], "field": "半导体/存储", "region": "国外"},
    {"name": "ASML", "aliases": ["asml"], "field": "半导体设备", "region": "国外"},
    {"name": "Broadcom", "aliases": ["broadcom", "博通"], "field": "AI芯片/网络", "region": "国外"},
    {"name": "Qualcomm", "aliases": ["qualcomm", "高通"], "field": "芯片/终端", "region": "国外"},
    {"name": "Micron", "aliases": ["micron", "美光"], "field": "存储芯片", "region": "国外"},
    {"name": "SK Hynix", "aliases": ["sk hynix", "hynix", "sk海力士", "海力士"], "field": "存储芯片", "region": "国外"},
    {"name": "Arm", "aliases": ["arm"], "field": "芯片IP", "region": "国外"},
    # 国外：LLM / 大模型
    {"name": "OpenAI", "aliases": ["openai"], "field": "LLM/AI", "region": "国外"},
    {"name": "Anthropic", "aliases": ["anthropic"], "field": "LLM/AI", "region": "国外"},
    {"name": "Google", "aliases": ["google", "谷歌"], "field": "LLM/AI芯片", "region": "国外"},
    {"name": "Meta", "aliases": ["meta"], "field": "LLM/AI", "region": "国外"},
    {"name": "Microsoft", "aliases": ["microsoft", "微软"], "field": "LLM/AI云", "region": "国外"},
    {"name": "xAI", "aliases": ["xai"], "field": "LLM/AI", "region": "国外"},
    {"name": "Tesla", "aliases": ["tesla", "特斯拉"], "field": "AI芯片/自动驾驶", "region": "国外"},
    # 国内：半导体 / AI 芯片
    {"name": "华为", "aliases": ["huawei", "华为", "海思"], "field": "AI芯片/半导体", "region": "国内"},
    {"name": "中芯国际", "aliases": ["smic", "中芯国际"], "field": "半导体制造", "region": "国内"},
    {"name": "寒武纪", "aliases": ["寒武纪", "cambricon"], "field": "AI芯片", "region": "国内"},
    {"name": "海光信息", "aliases": ["海光信息", "海光", "hygon"], "field": "AI芯片/CPU", "region": "国内"},
    {"name": "摩尔线程", "aliases": ["摩尔线程", "moore threads"], "field": "AI芯片/GPU", "region": "国内"},
    {"name": "壁仞科技", "aliases": ["壁仞", "biren"], "field": "AI芯片", "region": "国内"},
    {"name": "地平线", "aliases": ["地平线", "horizon robotics"], "field": "AI芯片/自动驾驶", "region": "国内"},
    {"name": "黑芝麻智能", "aliases": ["黑芝麻", "black sesame"], "field": "AI芯片/自动驾驶", "region": "国内"},
    # 国内：LLM / 大模型
    {"name": "DeepSeek", "aliases": ["deepseek", "深度求索"], "field": "LLM/AI", "region": "国内"},
    {"name": "月之暗面", "aliases": ["月之暗面", "moonshot", "kimi"], "field": "LLM/AI", "region": "国内"},
    {"name": "智谱", "aliases": ["智谱", "zhipu"], "field": "LLM/AI", "region": "国内"},
    {"name": "MiniMax", "aliases": ["minimax"], "field": "LLM/AI", "region": "国内"},
    {"name": "字节跳动", "aliases": ["bytedance", "字节跳动", "字节"], "field": "LLM/AI芯片", "region": "国内"},
    {"name": "阿里巴巴", "aliases": ["alibaba", "阿里巴巴", "阿里"], "field": "LLM/AI芯片", "region": "国内"},
    {"name": "百度", "aliases": ["baidu", "百度"], "field": "LLM/AI芯片", "region": "国内"},
    {"name": "腾讯", "aliases": ["tencent", "腾讯"], "field": "LLM/AI芯片", "region": "国内"},
]


def _alias_matches(alias: str, text: str) -> bool:
    """英文别名用词边界匹配，中文别名直接子串匹配。"""
    alias = alias.lower()
    if any(ord(ch) > 127 for ch in alias):
        return alias in text
    return re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", text) is not None


def _fetch_json_source(config, category, max_items=5, timeout=digest.DEFAULT_TIMEOUT):
    """JSON 接口源（新浪滚动 / 36氪热榜）→ 统一格式条目。"""
    name = config.get("name", "JSON源")
    kind, url = config.get("type"), config.get("url")
    headers = {"User-Agent": digest.USER_AGENT, "Content-Type": "application/json"}
    try:
        if kind == "sina_roll":
            resp = requests.get(url, headers=headers, timeout=timeout)
            entries = resp.json().get("result", {}).get("data", []) if resp.status_code == 200 else []
            pairs = [((e.get("title") or "").strip(), (e.get("url") or "").strip(), e.get("intro") or "")
                     for e in entries]
        elif kind == "36kr_hot":
            resp = requests.post(url, headers=headers, timeout=timeout,
                                 json={"partner_id": "web", "timestamp": 0,
                                       "param": {"siteId": 1, "platformId": 2}})
            entries = resp.json().get("data", {}).get("hotRankList", []) if resp.status_code == 200 else []
            pairs = []
            for e in entries:
                tm = e.get("templateMaterial") or {}
                item_id = e.get("itemId")
                reads = tm.get("statRead")
                pairs.append(((tm.get("widgetTitle") or "").strip(),
                              f"https://36kr.com/p/{item_id}" if item_id else "",
                              f"36氪热榜，阅读量约 {reads}" if reads else ""))
        else:
            print(f"⚠️ 未知 JSON 源类型 [{name}] {kind}")
            return []
    except Exception as e:
        print(f"⚠️ JSON 源抓取异常 [{name}] {type(e).__name__}: {e}")
        return []

    items = [digest.make_item(category, name, t, u, s) for t, u, s in pairs if t and u]
    return items[:max_items]


def fetch_all_feeds():
    """并发抓取 RSS + JSON 源（7 天时间窗 + 跨源去重），返回 (条目, 统计)。"""
    json_items = [
        item
        for category, sources in JSON_FEEDS.items()
        for config in sources
        for item in _fetch_json_source(config, category, max_items=5)
    ]
    return digest.collect(
        MODULE_FEEDS,
        extra_items=json_items,
        max_items_per_source=6,
        category_max_items=CATEGORY_MAX_ITEMS,
        timeout=25,
        summary_limit=900,
    )


# ---------------------------------------------------------------------------
# 3. 公司曝光度统计
# ---------------------------------------------------------------------------
def rank_companies(items: list, international_slots: int = 6, domestic_slots: int = 4):
    """按「本周抓取条目中提及该公司的条目数」统计曝光度并返回排行。"""
    counts = Counter()
    mentions = defaultdict(list)

    for item in items:
        text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
        for company in COMPANY_WATCHLIST:
            if any(_alias_matches(alias, text) for alias in company["aliases"]):
                counts[company["name"]] += 1
                mentions[company["name"]].append(item)

    ranked = sorted(
        [c for c in COMPANY_WATCHLIST if counts[c["name"]] > 0],
        key=lambda c: (-counts[c["name"]], c["name"]),
    )
    international = [c for c in ranked if c["region"] == "国外"][:international_slots]
    domestic = [c for c in ranked if c["region"] == "国内"][:domestic_slots]
    selected = international + domestic
    selected.sort(key=lambda c: (-counts[c["name"]], c["name"]))
    selected = selected[:international_slots + domestic_slots]

    return [(company, counts[company["name"]], mentions[company["name"]]) for company in selected]


def build_header(ranked: list) -> str:
    """确定性生成热度榜，数字不交给模型，避免模型改错。"""
    lines = [
        "# CompanyWatch 本周高曝光公司盘点",
        "",
        "> 基于本周抓取的真实新闻条目统计提及频次，综合国内与国际公司，聚焦半导体、AI 芯片与 LLM 领域。",
        "",
        "## 本周曝光热度榜",
        "",
        "| 排名 | 公司 | 领域 | 地域 | 本周提及条目数 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for idx, (company, count, _items) in enumerate(ranked, 1):
        lines.append(f"| {idx} | {company['name']} | {company['field']} | {company['region']} | {count} |")
    lines += ["", "## 重点公司速览", ""]
    return "\n".join(lines)


def build_company_context(ranked: list) -> str:
    """把高曝光公司及其相关真实条目整理成模型上下文。"""
    blocks = []
    for company, count, items in ranked:
        header = (
            f"【公司: {company['name']} | 领域: {company['field']} | "
            f"地域: {company['region']} | 本周提及条目数: {count}】"
        )
        related = digest.build_context(items[:5])
        blocks.append(f"{header}\n{related}")
    return "\n---\n".join(blocks)


def generate_briefing(ranked: list, stats: dict):
    print("2. 正在通过 DeepSeek 生成本周高曝光公司速览...")
    if not DEEPSEEK_API_KEY:
        print("⚠️ 未配置 DEEPSEEK_API_KEY，改为发送原始条目")
        return None

    company_context = build_company_context(ranked)
    exact_iso_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    briefing_prompt = f"""
你是一位严谨的全球科技产业分析师，负责写「本周高曝光科技公司速览」。
当前时间：{exact_iso_time}。

### 核心任务
基于下方【高曝光公司及真实相关新闻】，逐家公司写一段简洁、有信息量的速览。

================【高曝光公司及真实相关新闻】================
{company_context}
==========================================================

### 输出要求
公司顺序必须与上下文中给出的顺序一致。每家公司使用以下结构：

### 公司名（领域 · 地域）
先用 2-3 句话概括该公司本周被频繁提及的核心原因与重点方向；随后用 bullet 列出 1-4 条最相关的新闻：
- [上下文中的原始标题](上下文中的原始链接) — 用一句话说明该新闻事实。

### 事实与防幻觉铁律
- 公司定位可以用一句常识（例如 NVIDIA 是 GPU 与 AI 芯片公司），但本周动态、产品、融资、业绩、合作、具体数字必须来自上下文。
- 严禁调用训练记忆补写新闻、标题、链接或数据；链接必须逐字取自上下文。
- 若某条新闻缺少链接或标题，直接跳过。
- 中文说明为主，信息充分时每家公司 80-140 字，不注水、不编造。
- 直接输出 Markdown 公司章节，不要输出总标题、热度榜或代码围栏。
"""

    try:
        client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com",
            timeout=90.0,
        )
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": "你是严谨的全球科技产业分析师。公司定位可用常识，新闻事实必须逐字来自真实抓取上下文。"},
                {"role": "user", "content": briefing_prompt},
            ],
            temperature=0.0,
            stream=False,
        )

        if not response.choices:
            print(f"⚠️ DeepSeek 未返回 choices（模型 {DEEPSEEK_MODEL}），改为发送原始条目")
            return None

        md_content = response.choices[0].message.content
        if not md_content:
            print("⚠️ DeepSeek 返回的文本内容为空！")
            return None

        md_content = md_content.strip()
        if md_content.startswith("```markdown"):
            md_content = md_content[11:]
        elif md_content.startswith("```"):
            md_content = md_content[3:]
        if md_content.endswith("```"):
            md_content = md_content[:-3]

        print("✅ 本周高曝光公司速览生成成功！")
        return md_content.strip()
    except Exception as e:
        print(f"⚠️ DeepSeek 生成失败（模型 {DEEPSEEK_MODEL}，异常类型 {type(e).__name__}）: {e}")
        print("   完整堆栈如下，便于在 GitHub Actions / Mac mini 日志中定位：")
        traceback.print_exc()
        return None


def fallback_markdown(items, stats):
    return (
        "# 本期未生成 AI 简报\n\n"
        "> 未配置 DEEPSEEK_API_KEY 或模型返回空内容，以下是本期扫描到的原始条目，供直接查阅。\n\n"
        + digest.items_to_markdown(items, title=f"{FLOW_NAME} 本期条目")
    )


def ranked_items(ranked: list) -> list:
    """收集上榜公司相关的所有真实条目，用作 fallback 和链接校验白名单。"""
    seen, output = set(), []
    for _company, _count, items in ranked:
        for item in items:
            key = item.get("link") or item.get("title")
            if key and key not in seen:
                seen.add(key)
                output.append(item)
    return output


def main() -> int:
    date_str = datetime.now().strftime("%Y-%m-%d")
    items, stats = fetch_all_feeds()

    ranked = rank_companies(items)
    if not ranked:
        print("⚠️ 本周未识别到目标领域的高曝光公司，发送原始条目清单")
        md_content = fallback_markdown(items, stats)
    else:
        header = build_header(ranked)
        ai_md = generate_briefing(ranked, stats)
        if ai_md:
            md_content = f"{header}\n{ai_md}"
        else:
            related = ranked_items(ranked)
            md_content = header + "\n> AI 生成失败，以下为相关原始条目。\n\n" + digest.items_to_markdown(
                related, title="上榜公司相关条目"
            )

    md_content, safety = digest.validate_briefing(md_content, items)
    if safety["hallucinated"]:
        print(f"🛡️ 防幻觉校验：{safety['ok_links']}/{safety['total_links']} 个链接通过，"
              f"移除 {safety['hallucinated']} 个不可信链接")
        for _text, url in safety["removed"]:
            print(f"   ↳ 已移除: {url}")
        md_content += digest.hallucination_notice(safety)

    digest.save_backup(md_content, date_str,
                       os.path.join(BACKUP_DIR, f"{FLOW_NAME}_{date_str}.md"))

    html, plain_text = digest.render_email(
        brand_title=BRAND_TITLE, subtitle=SUBTITLE, footer=FOOTER,
        markdown_text=md_content, stats=stats, date_str=date_str,
    )
    ok = digest.send_email(
        f"{SUBJECT} ({date_str})", html, plain_text,
        attachments=[(f"{FLOW_NAME}-{date_str}-items.md", digest.items_to_markdown(items))],
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
