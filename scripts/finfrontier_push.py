import os
import sys
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
# 各方向模块每源抓取上限（差异化，平衡四方向）
CATEGORY_MAX_ITEMS = {
    "Macro_Markets": 3,
    "Quant_Trading": 4,
    "Fintech": 3,
    "Crypto": 4,
}

MODULE_FEEDS = {
    # === 宏观与市场 ===
    "Macro_Markets": {
        "CNBC Top News": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "MarketWatch Top Stories": "http://feeds.marketwatch.com/marketwatch/topstories/",
        "Financial Times Home": "https://www.ft.com/rss/home",
        "The Economist Finance": "https://www.economist.com/finance-and-economics/rss.xml",
        "Federal Reserve Press": "https://www.federalreserve.gov/feeds/press_all.xml",
        "Bloomberg Markets": "https://feeds.bloomberg.com/markets/news.rss",
        "Financial Times Alphaville": "https://www.ft.com/rss/alphaville",
        "Wolf Street": "https://wolfstreet.com/feed/",
        "ArXiv General Finance (q-fin.GN/EC)": "https://export.arxiv.org/api/query?search_query=cat:q-fin.GN+OR+cat:q-fin.EC&sortBy=submittedDate&sortOrder=descending&max_results=15",
    },

    # === 量化与算法交易 ===
    "Quant_Trading": {
        "Quantocracy": "https://quantocracy.com/feed/",
        "QuantPedia": "https://quantpedia.com/feed/",
        "Alpha Architect": "https://alphaarchitect.com/feed/",
        "ArXiv Quant Methods (q-fin.TR/PM/ST/CP/MF/PR/RM)": "https://export.arxiv.org/api/query?search_query=cat:q-fin.TR+OR+cat:q-fin.PM+OR+cat:q-fin.ST+OR+cat:q-fin.CP+OR+cat:q-fin.MF+OR+cat:q-fin.PR+OR+cat:q-fin.RM&sortBy=submittedDate&sortOrder=descending&max_results=20",
    },

    # === 金融科技 ===
    "Fintech": {
        "The Fintech Times": "https://thefintechtimes.com/feed/",
        "Finextra": "https://www.finextra.com/rss/headlines.aspx",
        "PYMNTS": "https://www.pymnts.com/feed/",
        "Crowdfund Insider": "https://www.crowdfundinsider.com/feed/",
    },

    # === 加密与数字资产 ===
    "Crypto": {
        "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "CoinTelegraph": "https://cointelegraph.com/rss",
        "Decrypt": "https://decrypt.co/feed",
        "The Block": "https://www.theblock.co/rss.xml",
    },
}

# ---------------------------------------------------------------------------
# 1. 抓取本 flow 的专属数据源
# ---------------------------------------------------------------------------
def fetch_all_feeds():
    """并发抓取全部源（7 天时间窗 + 跨源去重），返回 (条目, 统计)。

    每源条数上限沿用各板块原来的差异化配置 CATEGORY_MAX_ITEMS。
    """
    return digest.collect(MODULE_FEEDS, category_max_items=CATEGORY_MAX_ITEMS)


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
你是一位极度严谨的金融市场与量化研究编辑。
当前时间：{exact_iso_time}。

### 核心任务：
基于下方【真实抓取数据上下文】，整理一份【FinFrontier 每周金融、量化与市场前沿简报】。

================【真实抓取数据上下文】================
{real_news_context}
======================================================

### 重点关注的主题（优先提炼以下方向）：
1. **宏观经济与央行政策**：利率决议、通胀/就业/GDP 等关键经济数据、央行政策信号、大宗商品与汇率。
2. **量化与算法交易**：因子投资、统计套利、机器学习在金融中的应用、回测与执行算法、组合构建与风控。
3. **金融科技与市场结构**：支付、数字银行、清算结算、监管科技、市场微观结构变化。
4. **加密与数字资产**：BTC/ETH 等主流资产、DeFi、稳定币、ETF、监管与市场结构。
5. **学术研究 (q-fin)**：资产定价、风险建模、市场微观结构、计算金融、金融机器学习；论文按主题归入「宏观与市场」或「量化与算法交易」方向。

### 内容相关性筛选（逐条判定）：
本简报聚焦「金融市场的实质进展与可验证信号」，每条应至少满足以下之一：
- 有明确数据/数字支撑的市场、政策或宏观事件；
- 关于量化策略、因子、风控、金融机器学习的研究或深度技术文章；
- 有实质内容的金融科技或加密数字资产进展。

凡属于以下类型，一律整条剔除：
- 纯营销软文、广告、招聘信息、会议活动通知；
- 无任何数据或实质内容的标题党、重复性摘要；
- 与金融、市场、量化无关的普通公司动态。

### 核心防幻觉与事实审判法则：
1. **客观语气与进展限定**：严禁将“预测”、“推测”、“初步研究”撰写为“已经发生”或“确定结论”；对前瞻性观点必须标注为预期/预测。
2. **区分官方与第三方**：对于分析师观点、民间量化社区、非官方评测，必须明确标注“第三方/机构观点/预测”。
3. **静默跳过法则**：若某个方向在今日抓取数据中完全没有对应资讯，直接静默忽略该方向标题，严禁输出“无相关内容”。
4. **来源链接强制要求**：每条新闻/论文/发布必须在正文中以 Markdown 链接形式附上【真实抓取数据上下文】中的原始链接，格式为 `[文章标题](链接)`。若某条资讯在上下文中没有链接，或链接与内容对不上，直接整条剔除，严禁凭记忆补写链接、数字或来源名称。
5. **格式规范**：全局严禁使用任何项目符号（`-`、`*`）或数字列表序号（`1.`、`2.`）。代码片段必须包裹在标准 Markdown 代码块中。

---

### 输出结构（参考 Easyperf Newsletter 的 digest 风格，输出纯 Markdown 内容，切勿包裹全局 ```markdown）：

开头先写一行本期导语（不加标题、不加项目符号，直接一行自然句）：
"本期看点：……，以及更多。" 用 3-4 个短语点出本期最值得关注的点。

随后按「金融方向」分区，只保留真实上下文中确实有内容的方向，缺内容的方向整块标题静默删除：

## 宏观与市场 (Macro & Markets)
## 量化与算法交易 (Quant & Trading)
## 金融科技 (Fintech)
## 加密与数字资产 (Crypto & Digital Assets)

每条统一格式（正文段落，禁止用项目符号或编号列表）：
直接用 2-4 句话依次说明「这是什么 → 核心信息/数据 → 可验证的具体数字或事件（有则写准确数字）→ 局限或适用条件（如有）」，末尾统一用 `[文章标题](原始链接)` 收尾。

来源类型标注：每个方向内可混有官方新闻、量化博客与学术预印本，请在描述中用自然语言点明来源性质——官方发布直接陈述，第三方量化博客标注「第三方/机构观点」，arXiv 论文标注「预印本研究」；切勿把预印本结论写成确定事实。

链接规范（非常重要）：
- 链接文字必须使用该条目的【文章标题】，格式为 `[文章标题](原始链接)`，**严禁使用固定词 `原文`**。
- 若标题中含 `[`、`]`、`(`、`)`、`"` 等会破坏 Markdown 解析的特殊字符，请去除这些字符后再作为链接文字。
- 链接文字需与文章内容一致，严禁编造标题；若该条资讯在上下文中没有标题或链接，直接整条剔除。
- 每个板块标题 `##` 必须独占一行，严禁被前一条的链接或正文吞并。

风格要求：
- 精炼优先：每个方向最多只保留 2-3 条最有价值、最相关的内容，整份简报总条目控制在 8-10 条以内，严格「宁可少而精」，宁可整块留空也不要凑数。
- 每条都必须是「有实质内容的金融/市场进展」，宁可少而精，不要堆砌无关条目。
- 数据必须逐字取自上下文，严禁编造具体数字；对预测类信息明确标注预测属性。
- 可附一句克制的编辑点评，但必须基于上下文、客观中立，禁止编造观点。
- 所有链接必须逐字取自【真实抓取数据上下文】，缺链接或对不上则整条剔除。
"""

    try:
        briefing_response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": "你是一个严谨、苛刻的金融与市场核查编辑。只提炼真实上下文，绝不夸大事实，没有数据的板块直接跳过。"},
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
FLOW_NAME = "finfrontier"
SUBJECT = "【FinFrontier】每周金融、量化与市场前沿简报"
BRAND_TITLE = "💰 FinFrontier 每周金融、量化与市场前沿简报"
SUBTITLE = "金融、量化与市场前沿严谨跟踪"
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
