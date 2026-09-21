import os
import sys
import requests
from datetime import datetime

from openai import OpenAI

# 并发抓取 / 去重 / 渲染 / 发送等通用能力见 scripts/digest_common.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import digest_common as digest  # noqa: E402
# ---------------------------------------------------------------------------
# 读取环境变量
# ---------------------------------------------------------------------------
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.gmail.com")

try:
    EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "465"))
except ValueError:
    EMAIL_PORT = 465

EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER", "")

# ---------------------------------------------------------------------------
# 1. 各模块 Top 顶级数据源全量配置（按简报四板块组织）
# ---------------------------------------------------------------------------
# 国内科技公司动态：统一抓取科技媒体，由模型按公司领域归类输出
# 每源抓取上限（控制输入规模）
CATEGORY_MAX_ITEMS = {
    "Tech_News": 3,
}

MODULE_FEEDS = {
    # === 国内科技公司综合动态（模型按领域归类） ===
    "Tech_News": {
        "IT之家": "https://www.ithome.com/rss/",
        "爱范儿": "https://www.ifanr.com/feed",
        "极客公园": "https://www.geekpark.net/rss",
        "钛媒体": "https://www.tmtpost.com/rss.xml",
        "量子位": "https://www.qbitai.com/feed",
        "雷峰网": "https://www.leiphone.com/feed",
        "速途网": "https://www.sootoo.com/rss",
        "IT经理网": "https://www.ctocio.com/rss",
        "Solidot": "https://www.solidot.org/index.rss",
        "少数派": "https://sspai.com/feed",
        "OSCHINA": "https://www.oschina.net/news/rss",
        "InfoQ 中文": "https://www.infoq.cn/feed",
    },
}

# ---------------------------------------------------------------------------
# 1b. JSON 数据源（不走 RSS，直接请求官方/门户 JSON 接口）
# ---------------------------------------------------------------------------
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
# ---------------------------------------------------------------------------
# 1. 抓取本 flow 的专属数据源（RSS + JSON 接口）
# ---------------------------------------------------------------------------

def _fetch_json_source(config, category, max_items=3, timeout=digest.DEFAULT_TIMEOUT):
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
    max_items = CATEGORY_MAX_ITEMS.get("Tech_News", digest.DEFAULT_MAX_ITEMS_PER_SOURCE)
    json_items = [
        item
        for category, sources in JSON_FEEDS.items()
        for config in sources
        for item in _fetch_json_source(config, category, max_items=max_items)
    ]
    return digest.collect(MODULE_FEEDS, extra_items=json_items, max_items_per_source=max_items)


# 2. DeepSeek 生成文字简报
# ---------------------------------------------------------------------------
def generate_briefing(items, stats):
    real_news_context = digest.build_context(items)

    print("2. 正在通过 DeepSeek 提炼专业技术简报...")
    if not DEEPSEEK_API_KEY:
        print("⚠️ 未配置 DEEPSEEK_API_KEY，改为发送原始条目")
        return None

    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com"
    )

    exact_iso_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    briefing_prompt = f"""
你是一位极度严谨的中国科技产业观察者与编辑。
当前时间：{exact_iso_time}。

### 核心任务：
基于下方【真实抓取数据上下文】，整理一份【ChinaTech 国内科技公司动态简报】。

================【真实抓取数据上下文】================
{real_news_context}
======================================================

### 重点关注的主题（优先提炼以下方向）：
1. **互联网与平台**：字节跳动、腾讯、阿里、美团、京东、拼多多、快手、哔哩哔哩等公司的产品发布、组织调整、战略与业绩动态。
2. **智能硬件与消费电子**：华为、小米、OPPO、vivo、大疆、荣耀等公司的新品发布、供应链与市场份额动态。
3. **AI 与自动驾驶**：百度、DeepSeek、月之暗面、MiniMax、智谱、商汤，以及小鹏、理想、蔚来、地平线等公司在模型、智能驾驶上的进展。
4. **芯片与半导体**：华为海思、中芯国际、寒武纪、壁仞、沐曦等公司的制程、产品与国产替代进展。

### 内容相关性筛选（逐条判定）：
本简报聚焦「国内科技公司的实质动态」，每条应至少满足以下之一：
- 具体公司的新品发布、产品迭代、战略调整、组织/人事或业绩动态；
- 有实质内容的产业进展（芯片制程、大模型能力、智能驾驶等）；
- 国内科技公司相关的投融资、合作、监管影响等关键事件。

凡属于以下类型，一律整条剔除：
- 纯营销软文、广告、招聘信息、活动预告、二手资讯转述；
- 无公司主体、无实质内容的标题党或重复性摘要；
- 与国内科技公司无关的海外公司动态、生活类/泛娱乐内容。

### 核心防幻觉与事实审判法则：
1. **客观语气与进展限定**：严禁将“传闻”、“爆料”、“据称”、“可能”撰写为“已经发生”或“确定事实”；对未官宣内容必须明确标注为传闻/预测。
2. **区分官方与第三方**：官方发布直接陈述；媒体/第三方爆料、评测、分析必须标注“据媒体/第三方报道”。
3. **静默跳过法则**：若某个方向在今日抓取数据中完全没有对应资讯，直接静默忽略该方向标题，严禁输出“无相关内容”。
4. **来源链接强制要求**：每条动态必须在正文中以 Markdown 链接形式附上【真实抓取数据上下文】中的原始链接，格式为 `[原文](链接)`。若某条资讯在上下文中没有链接，或链接与内容对不上，直接整条剔除，严禁凭记忆补写链接、数字或公司名称。
5. **格式规范**：全局严禁使用任何项目符号（`-`、`*`）或数字列表序号（`1.`、`2.`）。代码片段必须包裹在标准 Markdown 代码块中。

---

### 输出结构（参考 Easyperf Newsletter 的 digest 风格，输出纯 Markdown 内容，切勿包裹全局 ```markdown）：

开头先写一行本期导语（不加标题、不加项目符号，直接一行自然句）：
"本期看点：……，以及更多。" 用 3-4 个短语点出本期最值得关注的点。

随后按「公司领域」分区，只保留真实上下文中确实有内容的方向，缺内容的方向整块标题静默删除：

## 互联网与平台 (Internet & Platforms)
## 智能硬件与消费电子 (Hardware & Consumer Electronics)
## AI 与自动驾驶 (AI & Autonomous Driving)
## 芯片与半导体 (Chips & Semiconductors)

每条统一格式（正文段落，禁止用项目符号或编号列表）：
直接用 2-4 句话依次说明「是什么公司 → 发生了什么 → 可验证的具体信息/数字 → 局限或未官宣之处（如有）」，末尾统一用 `[原文](原始链接)` 收尾。

来源类型标注：请在描述中用自然语言点明来源性质——官方发布直接陈述；媒体爆料/传闻标注“据媒体/第三方报道，尚未官宣”；严禁把传闻写成确定事实。

链接规范（非常重要）：
- 链接文字一律写固定词 `原文`，**严禁用文章标题作为链接文字**。标题常含 `[`、`]`、`(`、`"` 等特殊字符，会破坏 Markdown 解析。
- 若需点明条目标题，在描述正文中用普通文字自然写出即可，不要加粗、不要做成链接。
- 每个方向标题 `##` 必须独占一行，严禁被前一条的链接或正文吞并。

风格要求：
- 精炼优先：每个方向最多只保留 2-3 条最有价值、最相关的动态，整份简报总条目控制在 8-10 条以内，严格「宁可少而精」，宁可整块留空也不要凑数。
- 每条都必须是「有实质内容的国内科技公司动态」，宁可少而精，不要堆砌无关条目。
- 数据必须逐字取自上下文，严禁编造具体数字；对传闻/预测类信息明确标注属性。
- 可附一句克制的编辑点评，但必须基于上下文、客观中立，禁止编造观点。
- 所有链接必须逐字取自【真实抓取数据上下文】，缺链接或对不上则整条剔除。
"""

    try:
        briefing_response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": "你是一个严谨、苛刻的中国科技产业核查编辑。只提炼真实上下文，绝不夸大事实，没有数据的板块直接跳过。"},
                {"role": "user", "content": briefing_prompt}
            ],
            temperature=0.0,
            stream=False
        )

        md_content = briefing_response.choices[0].message.content.strip()
        if md_content.startswith("```markdown"):
            md_content = md_content[11:]
        elif md_content.startswith("```"):
            md_content = md_content[3:]
        if md_content.endswith("```"):
            md_content = md_content[:-3]

        print("✅ 多源简报文字生成成功！")
        return md_content.strip()
    except Exception as e:
        print(f"⚠️ DeepSeek 生成失败: {e}，改为发送原始条目")
        return None


# ---------------------------------------------------------------------------
# 3. 邮件渲染与发送 (已移除 MP3 附件逻辑)


# ---------------------------------------------------------------------------
# 3. 备份 / 渲染 / 发送（通用实现见 scripts/digest_common.py）
# ---------------------------------------------------------------------------
FLOW_NAME = "chinatech"
SUBJECT = "【ChinaTech】国内科技公司动态简报"
BRAND_TITLE = "🇨🇳 ChinaTech 国内科技公司动态简报"
SUBTITLE = "国内科技公司动态严谨跟踪"
FOOTER = "基于顶级数据源 & DeepSeek 零幻觉模式构建"
BACKUP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")


def fallback_markdown(items, stats):
    """DeepSeek 不可用时也照常发信：附上本期扫描到的原始条目，保证每次都有产出。"""
    return (
        "# 本期未生成 AI 简报\n\n"
        "> 未配置 DEEPSEEK_API_KEY 或模型返回空内容，以下是本期扫描到的原始条目，供直接查阅。\n\n"
        + digest.items_to_markdown(items, title=f"{FLOW_NAME} 本期条目")
    )


def main():
    date_str = datetime.now().strftime("%Y-%m-%d")
    items, stats = fetch_all_feeds()

    md_content = generate_briefing(items, stats)
    if not md_content:
        print("⚠️ 未生成 AI 简报，改为发送原始条目清单")
        md_content = fallback_markdown(items, stats)

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
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
