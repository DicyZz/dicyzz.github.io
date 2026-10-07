import os
import sys
import datetime
import traceback

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
# 1. 各模块 Top 顶级数据源全量配置（按简报四板块组织）
# ---------------------------------------------------------------------------
MODULE_FEEDS = {
    # === 新闻与发布 ===
    "News": {
        "Digitimes (semiconductor)": "https://www.digitimes.com/rss/daily.xml",
        "eeNews Europe (semiconductor)": "https://www.eenewseurope.com/en/feed/",
        "Phoronix Processors": "https://www.phoronix.com/rss.php",
        "LWN.net (Linux Kernel Direct)": "https://lwn.net/headlines/rss",
        "Kernel.org Releases": "https://www.kernel.org/feeds/kdist.xml",
        "SemiEngineering": "https://semiengineering.com/feed/",
        "Semiconductor Digest": "https://www.semiconductor-digest.com/feed/",
        "SemiWiki (semiconductor)": "https://semiwiki.com/feed/",
        "EE Times Global": "https://www.eetimes.com/feed/",
        "IEEE Spectrum Chips": "https://spectrum.ieee.org/feeds/topic/semiconductors.rss",
        "RISC-V International": "https://riscv.org/feed/",
        "LLVM Weekly": "https://llvmweekly.org/rss.xml",
        "OpenAI Research": "https://openai.com/news/rss.xml",
    },

    # === 深度文章 / 性能博客 ===
    "Blog_Posts": {
        "ACM SIGARCH (architecture)": "https://www.sigarch.org/feed/",
        "Brendan Gregg Performance Blog": "https://www.brendangregg.com/blog/rss.xml",
        "Chips and Cheese": "https://chipsandcheese.com/feed/",
        "DeepSpeed Blog": "https://www.deepspeed.ai/feed.xml",
        "Easyperf (Denis Bakhvalov)": "https://easyperf.net/feed.xml",
        "Fabian Giesen (ryg)": "https://fgiesen.wordpress.com/feed/",
        "Fabricated Knowledge (chips)": "https://fabricatedknowledge.substack.com/feed",
        "Glenn Klockwood (HPC/storage)": "https://blog.glennklockwood.com/feeds/posts/default",
        "Herb Sutter": "https://herbsutter.com/feed/",
        "High Scalability": "https://highscalability.com/feed/",
        "Hugging Face Blog": "https://huggingface.co/blog/feed.xml",
        "Jeff Preshing (concurrency/perf)": "https://preshing.com/feed/",
        "John Regehr (compilers)": "https://blog.regehr.org/feed/",
        "Johnny's Software Lab": "https://johnysswlab.com/feed/",
        "Lobsters (compilers)": "https://lobste.rs/t/compilers.rss",
        "Lobsters (performance)": "https://lobste.rs/t/performance.rss",
        "MaskRay (compiler/linker)": "https://maskray.me/blog/atom.xml",
        "Matt Godbolt (compilers/xania)": "https://xania.org/feed.atom",
        "Meta Engineering": "https://engineering.fb.com/feed/",
        "Netflix Tech Blog": "https://netflixtechblog.com/feed",
        "NVIDIA Developer Blog": "https://developer.nvidia.com/blog/feed/",
        "Paul E. McKenney (kernel/RCU)": "https://paulmck.livejournal.com/data/rss",
        "PyTorch Blog (ML systems)": "https://pytorch.org/blog/feed.xml",
        "Real World Tech": "https://www.realworldtech.com/feed/",
        "Rust Compiler & Performance": "https://blog.rust-lang.org/feed.xml",
        "Scientific Computing in Rust": "https://scientificcomputing.rs/monthly/rss.xml",
        "SemiAnalysis (chips/inference)": "https://semianalysis.com/feed/",
        "Simon Willison (LLM)": "https://simonwillison.net/atom/everything/",
        "The Chip Letter (Substack)": "https://thechipletter.substack.com/feed",
        "Travis Downs (perf analysis)": "https://travisdowns.github.io/feed.xml",
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


# ---------------------------------------------------------------------------
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
        base_url="https://api.deepseek.com",
        timeout=90.0
    )

    # 1. 先计算时间变量（确保 UTC 时区与 7 天窗口）
    now = datetime.datetime.now(datetime.timezone.utc)
    exact_iso_time = now.isoformat()
    seven_days_ago_time = (now - datetime.timedelta(days=7)).isoformat()

    briefing_prompt = f"""
你是一个严谨得近乎苛刻的系统架构师与 HPC/LLM 硬件加速专家，负责为技术团队撰写《PerfPulse 软硬件性能与架构简报》。
当前准确时间（UTC）：{exact_iso_time}。
本次简报检索时间窗口范围：{seven_days_ago_time} 至 {exact_iso_time}（仅限过去 7 天内发生的动态）。

### 核心任务：
基于下方【真实抓取数据上下文】，严格提取并整理一份【PerfPulse 每周架构与系统性能简报】。

================【真实抓取数据上下文】================
{real_news_context}
======================================================

### 🛑 铁律 1：绝对禁止幻觉与自由联想（最高优先级）
1. **来源限定**：开篇导语和正文中的所有技术点、产品名、数值、结论，**必须 100% 来源于上方的【真实抓取数据上下文】**。
2. **严禁扩写常识**：绝对禁止引入上下文中未提及的外部知识（例如正文没提到某技术，导语就绝对不能写）。如果正文没有足够亮点，宁可缩短导语，也绝不凭空编造。

### 重点关注的技术主题（优先提炼以下方向）：
1. **LLM 系统加速**：KV Cache 管理、Speculative Decoding、PagedAttention、Quantization (FP8/INT4/AWQ)、FlashAttention/FlashDecoding、vLLM/TensorRT-LLM 优化、Distributed Training/Inference (Pipeline/Tensor Parallelism)。
2. **CPU/GPU 微架构**：Cache Hierarchy (L1/L2/L3/SLC)、Branch Predictor、Out-of-Order Execution、ROB/Execution Units、Vector/Matrix Extensions (AVX-512, AMX, SVE, Tensor Cores)、Interconnect (NVLink, CXL, PCIe Gen6)。
3. **HPC 与编译优化**：LLVM/MLIR Passes、Loop Transformations (Tiling, Unrolling, Fusion)、Triton/TVM/XLA 代码生成、CUDA/ROCm/SYCL 内核优化、MPI/NCCL 通信重叠。
4. **Linux Kernel & Performance**：eBPF/XDP、io_uring、Memory Management (THP, NUMA balancing, ZSWAP)、Scheduler (EEVDF)、Filesystem/Block Layer (bcachefs, NVMe-oF)、perf/BPF 性能分析。
5. **半导体工艺与封装**：先进制程 (GAA/CFET/2nm)、光刻 (EUV/High-NA)、先进封装 (CoWoS/SoIC/Chiplet)、存储 (HBM/DRAM/NAND/3D)、晶圆代工与设备、器件物理。

### 🕒 时间窗口硬性过滤规则：
1. **严格 7 天限制**：逐条检查【真实抓取数据上下文】中每条资讯的发布时间。如果发布时间早于 {seven_days_ago_time}，或晚于当前时间 {exact_iso_time}，必须完全整条剔除。
2. **拒绝未来或跨代幻觉**：若原文或上下文中出现了不符合当前 2026 年实际时间逻辑的虚构版本号（如未发布的未来产品代际），一律视为无效噪音并丢弃。

### ⚡ 性能相关性强过滤（宁缺毋滥，静默剔除）：
本简报只收录「有明确技术机制或具体性能提升数据」的技术硬核内容。凡属于以下类型，**一律整条静默剔除，严禁收录，且不得输出“具体数据未披露”等废话说明**：
- 商业、营销、营收、市场预测、资本开支、创业竞赛、公关活动、展会开业；
- 政策建议、国家战略、生态演讲、政府/联合国发言、行业报告、社区拨款/人事变更；
- 无具体性能数据/无机制分析的普通产品发布、功能迭代、UI 升级、CMS 框架更新；
- 硬件评测与上手（笔记本/手机促销、主板/工作站/服务器/SSD/整机/网卡等外观或跑分评测，即使带 benchmark 数字也整条剔除）；
- 产品定价、涨价、促销、折扣、SKU 性价比/价值分析、市场行情；
- 厂商赞助或实验室营销软文（只有“X 倍提升 / 更高效”这类宣称，却无底层技术机制的软文）；
- 泛 IT 趣闻与非性能项目（手绘地图、TUI 客户端、IRC 聊天、Postgres/CSS 技巧）；
- 上层应用业务案例（法律、医疗、办公、车队管理、视频剪辑应用）；
- Web 开发、SaaS 应用、云服务规则（如 Cloudflare 规则、Turnstile、CDN 托管等）。
- 硬性数量上限：本期整篇最多保留 **16 条**；其中 `## 新闻与发布` 最多 8 条、`## 深度文章` 最多 6 条、`## 论文` 与 `## 其他资料` 各最多 4 条。超出部分按相关性从低到高静默删除，宁少勿多。

### 🛡️ 核心防幻觉与事实审判法则：
1. **静默跳过无数据说明**：如果某条资讯虽然沾边，但通篇只有“旨在提升性能”而没有写出具体的**底层机制**或**量化数据/对比基准**，**直接静默剔除该条**。
2. **区分民间与官方**：对于民间第三方开源项目、MOD 或非官方评测，正文必须明确标注“第三方社区项目/非官方测试”。
3. **动态板块选择**：只保留筛选后确实包含高质量条目的二级标题板块（`## 新闻与发布`、`## 深度文章`、`## 论文`、`## 其他资料`），若某个板块无符合标准的条目，直接彻底抹去该板块标题。
4. **来源链接强制要求**：每条正文必须在段落末尾附上【真实抓取数据上下文】中的原始链接，格式为 `[标题](链接)`。若某条资讯在上下文中缺少链接，整条剔除。
5. **格式规范**：全局严禁使用任何项目符号（`-`、`*`）或数字列表序号（`1.`、`2.`）。

### ✅ 输出前逐条自检（强制，最后一步执行）：
在写出最终内容前，逐条对照【真实抓取数据上下文】核对以下三点，任何一条不满足就整条删除：
1. 是否命中上方「性能相关性强过滤」的任一剔除类型？是 → 删除。
2. 是否写出了具体的底层机制或量化性能数据（数字 / 倍数 / 带宽 / 延迟）？否 → 删除。
3. 末尾链接是否 100% 来自【真实抓取数据上下文】？否 → 删除。
自检后若剩余条目数仍超过硬性上限，继续删除相关性最低的条目，直到满足上限为止。

---

### 输出结构（公众号排版优化版，输出纯 Markdown 内容，切勿包裹全局 ```markdown）：

开头导语（不加大标题，直接一段自然句，独占一行）：
本期看点：……，以及更多。（必须严格从下方最终保留的正文条目中提取 2-3 个真实亮点，绝对不准凭空编造）。

随后按「内容类型」分区（仅保留有内容的板块，标题前后各留一个空行）：

## 新闻与发布

## 深度文章

## 论文

## 其他资料

每条内容采用「加粗小标题 → 正文段落」两段式排版：
- 第一行：**加粗小标题**（概括该条核心，控制在 8-16 字，单独占一行，不要做成链接）；
- 第二行：正文段落（2-4 句话，说明「这是什么 → 核心优化机制/技术点 → 量化性能收益（如 **x 倍**、**百分比**、**GB/s**、**ms** 等）」。关键数字与倍数必须 **加粗**；
- 链接格式：直接跟在正文段落最后一句之后（不换行），形如 `……正文内容。[上下文中的原始标题](上下文中的原始链接)`；
- 条目与条目之间空一行。
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
        print(f"⚠️ DeepSeek 生成失败: {e}")
        traceback.print_exc()
        return None


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
    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
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
