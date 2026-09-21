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
# 1. 各模块 Top 顶级数据源全量配置（已扩充优质源）
# ---------------------------------------------------------------------------
CATEGORY_MAX_ITEMS = {
    "News": 4,
    "Blog_Posts": 6,
    "Research_Papers": 4,
    "Other_Materials": 6,
}

MODULE_FEEDS = {
    # === 新闻与发布 (实验室与大厂官方) ===
    "News": {
        "OpenAI News": "https://openai.com/news/rss.xml",
        "Google Blog (AI)": "https://blog.google/technology/ai/rss/",
        "Google DeepMind Blog": "https://deepmind.google/blog/rss.xml",
        "Google AI Blog": "https://research.google/blog/rss/",
        "Meta Engineering": "https://engineering.fb.com/feed/",
        "Microsoft Research Blog": "https://www.microsoft.com/en-us/research/feed/",
        "Hugging Face Blog": "https://huggingface.co/blog/feed.xml",
        "Google Developers Blog (Gemini)": "https://developers.googleblog.com/feeds/posts/default",
        "NVIDIA Developer Blog": "https://developer.nvidia.com/blog/feed/",
        "Apple Machine Learning Research": "https://machinelearning.apple.com/rss.xml",
        "AWS Machine Learning Blog": "https://aws.amazon.com/blogs/machine-learning/feed/",
    },

    # === 深度文章 / 技术博客 (权威学者与顶级学术机构) ===
    "Blog_Posts": {
        "Lil'Log (Lilian Weng)": "https://lilianweng.github.io/index.xml",
        "BAIR (Berkeley AI Research)": "https://bair.berkeley.edu/blog/feed.xml",
        "Together AI Blog": "https://www.together.ai/blog/rss.xml",
        "The Gradient": "https://thegradient.pub/rss/",
        "Import AI (Jack Clark)": "https://jack-clark.net/feed/",
        "Jay Alammar Blog": "https://jalammar.github.io/feed.xml",
        "Ahead of AI (Sebastian Raschka)": "https://magazine.sebastianraschka.com/feed",
        "Chip Huyen Blog": "https://huyenchip.com/feed.xml",
        "Simon Willison": "https://simonwillison.net/atom/everything/",
        "Eugene Yan": "https://eugeneyan.com/rss/",
        "Hacker News AI": "https://hnrss.org/newest?q=LLM+OR+agent+OR+multimodal",
    },

    # === 论文 (ArXiv 分类与学术聚合) ===
    "Research_Papers": {
        "ArXiv Machine Learning (cs.LG)": "http://export.arxiv.org/api/query?search_query=cat:cs.LG&sortBy=submittedDate&sortOrder=descending&max_results=20",
        "ArXiv Computation and Language (cs.CL)": "http://export.arxiv.org/api/query?search_query=cat:cs.CL&sortBy=submittedDate&sortOrder=descending&max_results=20",
        "ArXiv Artificial Intelligence (cs.AI)": "http://export.arxiv.org/api/query?search_query=cat:cs.AI&sortBy=submittedDate&sortOrder=descending&max_results=20",
        "ArXiv Computer Vision (cs.CV)": "http://export.arxiv.org/api/query?search_query=cat:cs.CV&sortBy=submittedDate&sortOrder=descending&max_results=20",
        "ArXiv Sound/Audio (cs.SD)": "http://export.arxiv.org/api/query?search_query=cat:cs.SD&sortBy=submittedDate&sortOrder=descending&max_results=20",
        "ArXiv Robotics (cs.RO)": "http://export.arxiv.org/api/query?search_query=cat:cs.RO&sortBy=submittedDate&sortOrder=descending&max_results=20",
        "Databricks Blog": "https://www.databricks.com/feed",
    },

    # === 其他资料（核心开源生态发布） ===
    "Other_Materials": {
        "Hugging Face Transformers Releases": "https://github.com/huggingface/transformers/releases.atom",
        "PyTorch GitHub Releases": "https://github.com/pytorch/pytorch/releases.atom",
        "vLLM GitHub Releases": "https://github.com/vllm-project/vllm/releases.atom",
        "SGLang GitHub Releases": "https://github.com/sgl-project/sglang/releases.atom",
        "llama.cpp GitHub Releases": "https://github.com/ggml-org/llama.cpp/releases.atom",
        "Ollama GitHub Releases": "https://github.com/ollama/ollama/releases.atom",
        "LangChain GitHub Releases": "https://github.com/langchain-ai/langchain/releases.atom",
        "DSPy GitHub Releases": "https://github.com/stanfordnlp/dspy/releases.atom",
        "Unsloth GitHub Releases": "https://github.com/unslothai/unsloth/releases.atom",
        "Microsoft DeepSpeed Releases": "https://github.com/microsoft/DeepSpeed/releases.atom",
        "AutoGen GitHub Releases": "https://github.com/microsoft/autogen/releases.atom",
    }
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
你是一位极度严谨的系统与硬件架构师兼科技编辑。
当前时间：{exact_iso_time}。

### 核心任务：
基于下方【真实抓取数据上下文】，整理一份【AIFrontier 每周 AI 模型、Agent 与多模态简报】。

================【真实抓取数据上下文】================
{real_news_context}
======================================================

### 重点关注的技术主题（优先提炼以下方向）：
1. **基础模型与前沿能力**：新模型发布与升级（LLM、多模态、视觉/语音/视频生成）、架构创新（MoE、SSM、长上下文、推理模型）、评测与 benchmark。
2. **Agent 与工具使用**：多智能体系统、ReAct/工具调用、function calling、记忆与规划、编码/浏览/操作类 Agent、评测基准（SWE-bench 等）。
3. **多模态与生成**：文生图/视频、语音、视觉-语言模型、图像/视频理解、跨模态对齐与统一架构。
4. **训练与数据**：数据集、训练方法（RLHF/DPO/SFT）、对齐与安全、scaling law、蒸馏、合成数据。

### 内容相关性筛选（逐条判定）：
本简报聚焦「模型能力与产品/研究新进展」，每条应至少满足以下之一：
- 新模型/新版本/新能力发布，含可验证的评测数据或能力描述；
- 关于 Agent、多模态、训练方法、对齐与安全的论文或深度技术文章；
- 有实质技术内容的开源发布或工具更新。

凡属于以下类型，一律整条剔除：
- 纯市场、融资、营收、股价、监管合规、政策等商业/非技术内容；
- 无技术细节的营销软文、会议活动通知、招聘信息；
- 与 AI 模型/Agent/多模态无关的普通软件发布。

### 核心防幻觉与事实审判法则：
1. **客观语气与进展限定**：严禁将“实验”、“讨论”、“初步探究”撰写为“成功落地”或“重大突破”。
2. **区分民间与官方**：对于民间第三方开源项目或非官方评测，必须明确标注“第三方社区/个人观点”。
3. **静默跳过法则**：若某个领域在今日抓取数据中完全没有对应资讯，直接静默忽略该板块标题，严禁输出“无相关内容”。
4. **来源链接强制要求**：每条新闻/论文/发布必须在正文中以 Markdown 链接形式附上【真实抓取数据上下文】中的原始链接，格式为 `[原文](链接)`。若某条资讯在上下文中没有链接，或链接与内容对不上，直接整条剔除，严禁凭记忆补写链接、PR 编号或开发者姓名。
5. **格式规范**：全局严禁使用任何项目符号（`-`、`*`）或数字列表序号（`1.`、`2.`）。代码片段必须包裹在标准 Markdown 代码块中。

---

### 输出结构（参考 Easyperf Newsletter 的 digest 风格，输出纯 Markdown 内容，切勿包裹全局 ```markdown）：

开头先写一行本期导语（不加标题、不加项目符号，直接一行自然句）：
"本期看点：……，以及更多。" 用 3-4 个短语点出本期最值得关注的点。

随后按「内容类型」分区，只保留真实上下文中确实有内容的板块，缺内容的板块整块标题静默删除：

## 新闻与发布 (News)
## 深度文章 (Blog Posts)
## 论文 (Research Papers)
## 其他资料 (Other Materials)

每条统一格式（正文段落，禁止用项目符号或编号列表）：
直接用 2-4 句话依次说明「这是什么 → 核心能力/技术点 → 可验证的评测数据或能力描述（有则写具体数字/榜单/基准）→ 局限或适用条件（如有）」，末尾统一用 `[原文](原始链接)` 收尾。

链接规范（非常重要）：
- 链接文字一律写固定词 `原文`，**严禁用文章标题作为链接文字**。标题常含 `[`、`]`、`(`、`"` 等特殊字符，会破坏 Markdown 解析。
- 若需点明条目标题，在描述正文中用普通文字自然写出即可，不要加粗、不要做成链接。
- 每个板块标题 `##` 必须独占一行，严禁被前一条的链接或正文吞并。

如为视频/工具类，链接文字可写 `原文` 或 `视频` / `GitHub` 等不含特殊字符的固定词。

风格要求：
- 精炼优先：每个板块最多只保留 2-4 条最有价值、最相关的内容，整份简报总条目控制在 8-10 条以内，严格「宁可少而精」，宁可整块留空也不要凑数。
- 每条都必须是「有实质内容的模型/研究进展」，宁可少而精，不要堆砌无关条目。
- 可附一句克制的编辑点评，但必须基于上下文、客观中立，禁止编造观点。
- 论文/第三方评测必须标注「第三方/社区」属性；未落地内容不得写成「重大突破」。
- 所有链接必须逐字取自【真实抓取数据上下文】，缺链接或对不上则整条剔除。
"""

    try:
        briefing_response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": "你是一个严谨、苛刻的技术核查编辑。只提炼真实上下文，绝不夸大事实，没有数据的板块直接跳过。"},
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
FLOW_NAME = "aifrontier"
SUBJECT = "【AIFrontier】每周 AI 模型、Agent 与多模态简报"
BRAND_TITLE = "🤖 AIFrontier 每周 AI 模型、Agent 与多模态简报"
SUBTITLE = "AI 模型、Agent 与多模态前沿严谨跟踪"
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
