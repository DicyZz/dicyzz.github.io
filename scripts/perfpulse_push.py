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
MODULE_FEEDS = {
    # === 新闻与发布 ===
    "News": {
        "Phoronix Processors": "https://www.phoronix.com/rss.php",
        "LWN.net (Linux Kernel Direct)": "https://lwn.net/headlines/rss",
        "Kernel.org Releases": "https://www.kernel.org/feeds/kdist.xml",
        "SemiEngineering": "https://semiengineering.com/feed/",
        "The Next Platform": "https://www.nextplatform.com/feed/",
        "EE Times Global": "https://www.eetimes.com/feed/",
        "IEEE Spectrum Chips": "https://spectrum.ieee.org/feeds/topic/semiconductors.rss",
        "ServeTheHome (STH)": "https://www.servethehome.com/feed/",
        "RISC-V International": "https://riscv.org/feed/",
        "LLVM Weekly": "https://llvmweekly.org/rss.xml",
        "OpenAI Research": "https://openai.com/news/rss.xml",
        "Google AI Blog": "https://research.google/blog/rss/",
    },

    # === 深度文章 / 性能博客 ===
    "Blog_Posts": {
        "Brendan Gregg Performance Blog": "https://www.brendangregg.com/blog/rss.xml",
        "Easyperf (Denis Bakhvalov)": "https://easyperf.net/feed.xml",
        "Chips and Cheese": "https://chipsandcheese.com/feed/",
        "TechPowerUp": "https://www.techpowerup.com/rss/news",
        "MaskRay (compiler/linker)": "https://maskray.me/blog/atom.xml",
        "Johnny's Software Lab": "https://johnysswlab.com/feed/",
        "Fabian Giesen (ryg)": "https://fgiesen.wordpress.com/feed/",
        "Herb Sutter": "https://herbsutter.com/feed/",
        "Real World Tech": "https://www.realworldtech.com/feed/",
        "Travis Downs (perf analysis)": "https://travisdowns.github.io/feed.xml",
        "Jeff Preshing (concurrency/perf)": "https://preshing.com/feed/",
        "John Regehr (compilers)": "https://blog.regehr.org/feed/",
        "Paul E. McKenney (kernel/RCU)": "https://paulmck.livejournal.com/data/rss",
        "High Scalability": "https://highscalability.com/feed/",
        "SemiAnalysis (chips/inference)": "https://semianalysis.com/feed/",
        "Matt Godbolt (compilers/xania)": "https://xania.org/feed.atom",
        "The Chip Letter (Substack)": "https://thechipletter.substack.com/feed",
        "Lobsters (performance)": "https://lobste.rs/t/performance.rss",
        "Lobsters (compilers)": "https://lobste.rs/t/compilers.rss",
        "Glenn Klockwood (HPC/storage)": "https://blog.glennklockwood.com/feeds/posts/default",
        "Scientific Computing in Rust": "https://scientificcomputing.rs/monthly/rss.xml",
        "Cloudflare Tech Blog": "https://blog.cloudflare.com/rss/",
        "Netflix Tech Blog": "https://netflixtechblog.com/feed",
        "Hugging Face Blog": "https://huggingface.co/blog/feed.xml",
        "Databricks Engineering": "https://www.databricks.com/feed",
        "DeepSpeed Blog": "https://www.deepspeed.ai/feed.xml",
        "NVIDIA Developer Blog": "https://developer.nvidia.com/blog/feed/",
        "Meta Engineering": "https://engineering.fb.com/feed/",
        "Rust Compiler & Performance": "https://blog.rust-lang.org/feed.xml",
        "Tom's Hardware": "https://www.tomshardware.com/feeds/all",
    },

    # === 论文 ===
    "Research_Papers": {
        "ArXiv Machine Learning (cs.LG)": "http://export.arxiv.org/api/query?search_query=cat:cs.LG&sortBy=submittedDate&sortOrder=descending&max_results=10",
        "ArXiv Computation and Language (cs.CL)": "http://export.arxiv.org/api/query?search_query=cat:cs.CL&sortBy=submittedDate&sortOrder=descending&max_results=10",
        "ArXiv Artificial Intelligence (cs.AI)": "http://export.arxiv.org/api/query?search_query=cat:cs.AI&sortBy=submittedDate&sortOrder=descending&max_results=10",
        "ArXiv Computer Architecture (cs.AR)": "http://export.arxiv.org/api/query?search_query=cat:cs.AR&sortBy=submittedDate&sortOrder=descending&max_results=10",
        "ArXiv Distributed Computing (cs.DC)": "http://export.arxiv.org/api/query?search_query=cat:cs.DC&sortBy=submittedDate&sortOrder=descending&max_results=10",
        "ArXiv Performance Evaluation (cs.PF)": "http://export.arxiv.org/api/query?search_query=cat:cs.PF&sortBy=submittedDate&sortOrder=descending&max_results=10",
    },

    # === 其他资料（发布、工具、聚合） ===
    "Other_Materials": {
        "vLLM GitHub Releases": "https://github.com/vllm-project/vllm/releases.atom",
        "TensorRT-LLM GitHub Releases": "https://github.com/NVIDIA/TensorRT-LLM/releases.atom",
        "llama.cpp GitHub Releases": "https://github.com/ggml-org/llama.cpp/releases.atom",
        "NVIDIA TensorRT Releases": "https://github.com/NVIDIA/TensorRT/releases.atom",
        "Hacker News Systems Tech": "https://news.ycombinator.com/rss",
    }
}

# ---------------------------------------------------------------------------
# 1. 抓取本 flow 的专属数据源
# ---------------------------------------------------------------------------
def fetch_all_feeds():
    """并发抓取全部源（7 天时间窗 + 跨源去重），返回 (条目, 统计)。"""
    return digest.collect(MODULE_FEEDS)


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
基于下方【真实抓取数据上下文】，整理一份【PerfPulse 每周架构与系统性能简报】。

================【真实抓取数据上下文】================
{real_news_context}
======================================================

### 重点关注的技术主题（优先提炼以下方向）：
1. **LLM 系统加速**：KV Cache 管理、Speculative Decoding、PagedAttention、Quantization (FP8/INT4/AWQ)、FlashAttention/FlashDecoding、vLLM/TensorRT-LLM 优化、Distributed Training/Inference (Pipeline/Tensor Parallelism)。
2. **CPU/GPU 微架构**：Cache Hierarchy (L1/L2/L3/SLC)、Branch Predictor、Out-of-Order Execution、ROB/Execution Units、Vector/Matrix Extensions (AVX-512, AMX, SVE, Tensor Cores)、Interconnect (NVLink, CXL, PCIe Gen6)。
3. **HPC 与编译优化**：LLVM/MLIR Passes、Loop Transformations (Tiling, Unrolling, Fusion)、Triton/TVM/XLA 代码生成、CUDA/ROCm/SYCL 内核优化、MPI/NCCL 通信重叠。
4. **Linux Kernel & Performance**：eBPF/XDP、io_uring、Memory Management (THP, NUMA balancing, ZSWAP)、Scheduler (EEVDF)、Filesystem/Block Layer (bcachefs, NVMe-oF)、perf/BPF 性能分析。

### 性能相关性强过滤（最高优先级，逐条判定）：
本简报只收录「与性能提升直接相关」的内容，即必须至少满足以下之一：
- 包含具体的性能收益数据（吞吐、延迟、IPC、带宽、功耗、编译/训练/推理耗时等）；
- 描述可落地的优化技术或机制（Cache/流水线/并行化/量化/KV Cache/调度/编译器 Pass/内核调优等）；
- 是针对上述方向的论文、开源发布或 benchmark。

凡属于以下类型，一律整条剔除，不得收录：
- 市场预测、营收、资本开支、数据中心需求等商业话题（如 Dell/HPE 预测）；
- 政策建议、国家战略、生态演讲、行业报告等非技术内容；
- 仅有功能发布/换壳升级、无性能数据的普通产品发布（如交换机、媒体服务器）；
- 与性能无关的 bugfix、AI 治理、合规类新闻。

### 核心防幻觉与事实审判法则：
1. **客观语气与进展限定**：严禁将“实验”、“讨论”、“初步探究”撰写为“成功落地”或“重大突破”。
2. **区分民间与官方**：对于民间第三方开源项目或非官方评测，必须明确标注“第三方社区/个人观点”。
3. **静默跳过法则**：若某个领域在今日抓取数据中完全没有对应资讯，直接静默忽略该板块标题，严禁输出“无相关内容”。
4. **来源链接强制要求**：每条新闻/论文/发布必须在正文中以 Markdown 链接形式附上【真实抓取数据上下文】中的原始链接，格式为 `[标题](链接)`。若某条资讯在上下文中没有链接，或链接与内容对不上，直接整条剔除，严禁凭记忆补写链接、PR 编号或开发者姓名。
5. **格式规范**：全局严禁使用任何项目符号（`-`、`*`）或数字列表序号（`1.`、`2.`）。代码片段必须包裹在标准 Markdown 代码块中。

---

### 输出结构（公众号排版优化版，输出纯 Markdown 内容，切勿包裹全局 ```markdown）：

开头导语（不加大标题，直接一段自然句，独占一行）：
用一句「本期看点：……，以及更多。」点出 3-4 个本期最值得关注的点。

随后按「内容类型」分区，只保留真实上下文中确实有内容的板块，缺内容的板块整块标题静默删除。板块标题用二级标题，标题前后各留一个空行：

## 新闻与发布
## 深度文章
## 论文
## 其他资料

每条内容采用「加粗小标题 → 正文段落」两段式排版（公众号阅读友好）：
- 先用一行 **加粗小标题** 概括该条核心，控制在 8-16 字，可直接取自原文标题或自行提炼，加粗后单独占一行；
- 紧接着一个正文段落（2-4 句话），依次说明「这是什么 → 核心优化机制/技术点 → 量化性能收益（尽量写具体数字，如 x 倍、百分比、带宽/延迟数值）→ 局限或适用条件（如有）」，其中的关键性能数字、倍数、百分比用 **加粗** 强调；
- 链接直接跟在正文段落末尾，与正文同属一个段落，不单独换行、不单独占一行；
- 条目之间用一个空行分隔。

链接规范（非常重要）：
- 链接文字使用原文标题名（即【真实抓取数据上下文】中该条的「标题」），不要用固定词「原文」。
- 若原文标题含有会破坏 Markdown 的字符（`[`、`]`、`(`、`)`、`*`、`_`、`"`、`<`、`>` 等），须在链接文字中将其删除或替换为空格/全角字符，确保 `[标题](链接)` 能正确解析；禁止让标题中的特殊字符原样出现在链接文字内。
- 链接写在正文段落末尾，紧跟最后一句，形如「……正文内容。 [标题名](原始链接)」。
- 加粗小标题用文字呈现即可，不要做成链接。
- 每个板块标题 `##` 必须独占一行，严禁被前一条的链接或正文吞并。

风格要求（公众号排版）：
- 每条都必须是「性能干货」，宁可少而精，不要堆砌无关条目。
- 正文用短句，每段控制在 2-4 句，便于手机竖屏扫读；关键数字、倍数、百分比、结论必须加粗。
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
FLOW_NAME = "perfpulse"
SUBJECT = "【PerfPulse】每周硬件、微架构与 LLM 性能简报"
BRAND_TITLE = "⚡ PerfPulse 每周微架构、系统与 HPC 简报"
SUBTITLE = "真实硬件、LLM 加速与 Linux Kernel 严谨跟踪"
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
