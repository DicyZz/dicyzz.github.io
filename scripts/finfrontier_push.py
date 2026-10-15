import os
import sys
import traceback
from datetime import datetime, timezone, timedelta

from openai import OpenAI

# 并发抓取 / 去重 / 渲染 / 发送等通用能力见 scripts/digest_common.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import digest_common as digest  # noqa: E402

# ---------------------------------------------------------------------------
# 读取环境变量
# ---------------------------------------------------------------------------
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.gmail.com")

try:
    EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "465"))
except ValueError:
    EMAIL_PORT = 465

EMAIL_SENDER = os.environ.get("EMAIL_SENDER", "")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER", "")

# ---------------------------------------------------------------------------
# 1. 各模块 Top 顶级数据源全量配置（已剔除易卡顿的慢速 ArXiv API，确保 15s 内响应）
# ---------------------------------------------------------------------------
CATEGORY_MAX_ITEMS = {
    "Macro_Markets": 4,
    "Quant_Trading": 4,
    "Fintech": 3,
    "Crypto": 4,
}

MODULE_FEEDS = {
    # === 宏观与市场 ===
    "Macro_Markets": {
        "Federal Reserve Monetary Policy": "https://www.federalreserve.gov/feeds/press_monetary.xml",
        "European Central Bank Press": "https://www.ecb.europa.eu/rss/press.html",
        "Bank for International Settlements (BIS)": "https://www.bis.org/docmail/bis_press.xml",
        "Financial Times Alphaville": "https://www.ft.com/rss/alphaville",
        "CNBC Top News": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "MarketWatch Top Stories": "http://feeds.marketwatch.com/marketwatch/topstories/",
        "The Economist Finance": "https://www.economist.com/finance-and-economics/rss.xml",
    },

    # === 量化与算法交易 ===
    "Quant_Trading": {
        "AQR Insights": "https://www.aqr.com/Insights/RSS",
        "Man Group Insights": "https://www.man.com/rss/insights",
        "Quantocracy": "https://quantocracy.com/feed/",
        "QuantPedia": "https://quantpedia.com/feed/",
        "Alpha Architect": "https://alphaarchitect.com/feed/",
    },

    # === 金融科技与市场结构 ===
    "Fintech": {
        "Finextra Headlines": "https://www.finextra.com/rss/headlines.aspx",
        "The Fintech Times": "https://thefintechtimes.com/feed/",
        "Bank of England Research & Publications": "https://www.bankofengland.co.uk/rss/publications",
        "SEC Press Releases": "https://www.sec.gov/news/pressreleases.rss",
    },

    # === 加密与数字资产 ===
    "Crypto": {
        "Paradigm Research": "https://www.paradigm.xyz/rss.xml",
        "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "The Block": "https://www.theblock.co/rss.xml",
        "Decrypt": "https://decrypt.co/feed",
    },
}

# ---------------------------------------------------------------------------
# 1. 抓取本 flow 的专属数据源
# ---------------------------------------------------------------------------
def fetch_all_feeds():
    """并发抓取全部源（7 天时间窗 + 跨源去重），返回 (条目, 统计)。"""
    print("1. 开始并发拉取 RSS 数据源...")
    try:
        items, stats = digest.collect(MODULE_FEEDS, category_max_items=CATEGORY_MAX_ITEMS)
        print(f"   ✅ 抓取完成：共获取 {len(items)} 条有效条目")
        return items, stats
    except Exception as e:
        print(f"⚠️ 抓取过程发生异常: {e}")
        traceback.print_exc()
        return [], {}


# ---------------------------------------------------------------------------
# 2. DeepSeek 生成文字简报
# ---------------------------------------------------------------------------
def generate_briefing(items, stats):
    if not items:
        print("⚠️ 没有可用的抓取条目，跳过 AI 简报生成。")
        return None

    # 防止条目过多导致 Token 超限或响应变慢，最多截取前 35 条核心内容
    if len(items) > 35:
        print(f"⚠️ 当前条目数 ({len(items)}) 较多，自动截断前 35 条核心内容以防超限...")
        items = items[:35]

    real_news_context = digest.build_context(items)

    print("2. 正在通过 DeepSeek 提炼专业金融简报...")
    if not DEEPSEEK_API_KEY:
        print("⚠️ 未配置 DEEPSEEK_API_KEY，改为发送原始条目")
        return None

    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com",
        timeout=90.0
    )

    now = datetime.now(timezone.utc)
    exact_iso_time = now.strftime("%Y-%m-%d %H:%M:%S UTC")
    seven_days_ago_time = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S UTC")

    briefing_prompt = f"""
你是一位极度严谨的金融市场与量化研究编辑。
当前准确时间（UTC）：{exact_iso_time}。
检索时间窗口范围：{seven_days_ago_time} 至 {exact_iso_time}（仅限过去 7 天内发生的动态）。

### 核心任务：
基于下方【真实抓取数据上下文】，整理一份【FinFrontier 每周金融,量化与市场前沿简报】。

================【真实抓取数据上下文】================
{real_news_context}
======================================================

### 重点关注的主题（优先提炼以下方向）：
1. **宏观经济与央行政策**：利率决议,通胀/就业/GDP 等关键经济数据,央行政策信号,大宗商品与汇率。
2. **量化与算法交易**：因子投资,统计套利,机器学习在金融中的应用,回测与执行算法,组合构建与风控。
3. **金融科技与市场结构**：支付,数字银行,清算结算,监管科技,市场微观结构变化。
4. **加密与数字资产**：BTC/ETH 等主流资产,DeFi,稳定币,MEV,密码学,监管与市场结构。

### 🛑 铁律 1：绝对禁止幻觉与自由联想（最高优先级）
- 你只能转述【真实抓取数据上下文】中明确出现的信息；公司名,产品名,事件,数字,日期,链接都必须在上下文中能逐字找到对应出处。
- 上下文里没有的内容一律视为「不存在」。严禁调用你自身训练数据中的任何知识来补写,扩写或推测新闻事件。
- 每条动态必须能回溯到上下文中的某条原始「标题 + 链接」,二者缺一即整条删除。

### ⚡ 内容相关性筛选（逐条判定,宁缺毋滥）：
本简报聚焦「金融市场的实质进展与可验证信号」，每条应至少满足以下之一：
- 有明确数据/数字支撑的市场,政策或宏观事件；
- 关于量化策略,因子,风控,金融机器学习的研究或深度技术文章；
- 有实质内容的金融科技或加密数字资产进展。

凡属于以下类型,一律整条静默剔除：
- 纯营销软文,广告,招聘信息,会议活动通知,展会；
- 无任何数据或实质内容的标题党,重复性摘要；
- 与金融,市场,量化无关的普通公司动态。

### 🛡️ 核心防幻觉与事实审判法则：
1. **客观语气与进展限定**：严禁将“预测”,“推测”撰写为“已经发生”或“确定结论”；对前瞻性观点必须标注为预期/预测。
2. **区分官方与第三方**：对于分析师观点,民间量化社区,必须明确标注“第三方/机构观点/预测”。
3. **静默跳过法则**：若某个方向在今日抓取数据中完全没有对应资讯,直接静默忽略该方向标题,严禁输出“无相关内容”等废话。
4. **来源链接强制要求**：每条新闻/论文/发布必须在正文中以 Markdown 链接形式附上【真实抓取数据上下文】中的原始链接,格式为 `[文章标题](链接)`。若某条资讯在上下文中没有链接,或链接与内容对不上,直接整条剔除。
5. **格式规范**：全局严禁使用任何项目符号（`-`,`*`）或数字列表序号（`1.`,`2.`）。

---

### 输出结构（输出纯 Markdown 内容,切勿包裹全局 ```markdown）：

开头先写一行本期导语（不加标题,不加项目符号,直接一行自然句）：
本期看点：……，以及更多。（必须严格从下方最终保留的正文条目中提取 2-3 个真实亮点,绝对不准凭空编造）。

随后按板块分区（只保留真实上下文中确实有内容的板块,缺内容的板块整块标题静默删除）：

## 宏观与市场 (Macro & Markets)
## 量化与算法交易 (Quant & Trading)
## 金融科技 (Fintech)
## 加密与数字资产 (Crypto & Digital Assets)

每条统一格式（正文段落,禁止用项目符号或编号列表）：
直接用 2-4 句话依次说明「这是什么 → 核心信息/数据 → 可验证的具体数字或事件」，末尾统一跟上 `[上下文中的原始标题](上下文中的原始链接)`，不单独换行。

风格要求：
- 精炼优先：每个方向最多保留 4 条最有价值,最相关的内容，整份简报总条目控制在 12-16 条以内。
- 所有链接必须逐字取自【真实抓取数据上下文】，缺链接或对不上则整条剔除。
"""

    try:
        briefing_response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": "你是一个严谨,苛刻的金融与市场核查编辑。只提炼真实上下文,绝不夸大事实,没有数据的板块直接跳过。"},
                {"role": "user", "content": briefing_prompt}
            ],
            temperature=0.0,
            stream=False
        )

        if not briefing_response.choices:
            print("⚠️ DeepSeek 返回了空的 choices 列表！")
            return None

        md_content = briefing_response.choices[0].message.content
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

        print("✅ 多源简报文字生成成功！")
        return md_content.strip()
    except Exception as e:
        print(f"⚠️ DeepSeek 生成失败: {e}")
        traceback.print_exc()
        return None


# ---------------------------------------------------------------------------
# 3. 备份 / 渲染 / 发送
# ---------------------------------------------------------------------------
FLOW_NAME = "finfrontier"
SUBJECT = "【FinFrontier】每周金融、量化与市场前沿简报"
BRAND_TITLE = "💰 FinFrontier 每周金融、量化与市场前沿简报"
SUBTITLE = "金融、量化与市场前沿严谨跟踪"
FOOTER = "基于顶级数据源 & DeepSeek 零幻觉模式构建"
BACKUP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")


def fallback_markdown(items, stats):
    return (
        "# 本期未生成 AI 简报\n\n"
        "> 未配置 DEEPSEEK_API_KEY 或模型返回空内容，以下是本期扫描到的原始条目，供直接查阅。\n\n"
        + digest.items_to_markdown(items, title=f"{FLOW_NAME} 本期条目")
    )


def main():
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    items, stats = fetch_all_feeds()

    md_content = generate_briefing(items, stats)
    if not md_content:
        print("⚠️ 未生成 AI 简报，改为发送原始条目清单")
        md_content = fallback_markdown(items, stats)

    md_content, safety = digest.validate_briefing(md_content, items)
    if safety.get("hallucinated", 0) > 0:
        print(f"🛡️ 防幻觉校验：{safety.get('ok_links', 0)}/{safety.get('total_links', 0)} 个链接通过，"
              f"移除 {safety.get('hallucinated', 0)} 个不可信链接")
        for _text, url in safety.get("removed", []):
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
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
