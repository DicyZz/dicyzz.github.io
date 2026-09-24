import argparse
import json
import os
import sys
import tempfile
from datetime import datetime

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
# Flow 元信息
# ---------------------------------------------------------------------------
FLOW_NAME = "chipschool"
SUBJECT = "【芯片通识课】半导体基础科普"
BRAND_TITLE = "🔬 芯片通识课 · 半导体基础科普"
SUBTITLE = "从基础讲起，每讲一个主题"
FOOTER = "知识部分只讲教科书级共识 · 新闻实例逐条来自真实抓取 · DeepSeek 生成"

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(REPO_ROOT, "data")
STATE_FILE = os.path.join(DATA_DIR, "chipschool_state.json")
BACKUP_DIR = os.path.join(REPO_ROOT, "output")

# ---------------------------------------------------------------------------
# 系列大纲（15 讲，5 个阶段）。结构硬编码，保证系列稳定；LLM 只负责扩写。
# ---------------------------------------------------------------------------
LESSONS = [
    # —— 第一阶段：基础概念 ——
    {"no": 1, "title": "半导体是什么：导体、绝缘体与半导体的分野", "phase": "基础概念", "points": [
        "用「导电的难易」给材料分类：导体、绝缘体、半导体",
        "能带理论：价带、导带与带隙（禁带）是什么",
        "硅为什么是最主流的半导体材料（储量、氧化物、温度特性）",
        "半导体的独特之处：掺杂可以控制导电性",
    ]},
    {"no": 2, "title": "硅的旅程：从沙粒到单晶硅与晶圆", "phase": "基础概念", "points": [
        "从石英砂到多晶硅的提纯过程（冶金级 → 电子级）",
        "单晶硅的生长：CZ 拉晶法（直拉法）是什么",
        "晶圆（wafer）的切割、抛光与规格（尺寸、厚度）",
        "为什么晶圆越做越大（成本摊薄与良率）",
    ]},
    {"no": 3, "title": "PN 结与二极管：半导体器件的起点", "phase": "基础概念", "points": [
        "掺杂：N 型（多电子）与 P 型（多空穴）",
        "PN 结的形成与耗尽区",
        "二极管的单向导电性：正向导通、反向截止",
        "二极管在整流、稳压、发光（LED）中的基本用途",
    ]},

    # —— 第二阶段：核心器件 ——
    {"no": 4, "title": "晶体管：从 BJT 到 MOSFET，再到 FinFET 与 GAA", "phase": "核心器件", "points": [
        "晶体管是「电子开关」：用电压控制电流通断",
        "BJT（双极型晶体管）与 MOSFET（场效应管）的区别",
        "MOSFET 的基本结构：栅极、源极、漏极、沟道",
        "为什么 FinFET 取代平面 MOSFET，GAA 又是什么",
    ]},
    {"no": 5, "title": "CMOS 逻辑门：芯片里的 0 和 1 是怎么算出来的", "phase": "核心器件", "points": [
        "CMOS 为什么是互补金属氧化物半导体（NMOS + PMOS）",
        "用 CMOS 搭出非门、与门、或门等基本逻辑门",
        "0 和 1 如何通过电压高低表示",
        "为什么 CMOS 功耗低：静态功耗几乎为零",
    ]},
    {"no": 6, "title": "存储器件：DRAM、NAND Flash 与 SRAM", "phase": "核心器件", "points": [
        "存储器在芯片里的角色：临时工作区 vs 长期存储",
        "DRAM：电容充放电存储，需要周期性刷新",
        "NAND Flash：闪存如何「记住」数据，为什么断电不丢",
        "SRAM：速度快但贵，常用作 CPU 缓存",
    ]},

    # —— 第三阶段：制造与设计 ——
    {"no": 7, "title": "光刻：如何在硅片上「雕刻」出几十亿个晶体管", "phase": "制造与设计", "points": [
        "光刻的基本原理：像「投影照相」把图案印到晶圆上",
        "光刻胶、掩膜版与曝光的基本流程",
        "DUV（深紫外）与 EUV（极紫外）光刻的区别",
        "为什么制程越先进，光刻越难（分辨率、光源波长）",
    ]},
    {"no": 8, "title": "刻蚀、沉积与离子注入：一层一层「盖楼」的工艺", "phase": "制造与设计", "points": [
        "芯片制造是反复的「加材料、减材料、改性质」循环",
        "刻蚀：干法刻蚀与湿法刻蚀各用于什么",
        "沉积：CVD、PVD 如何长出薄膜",
        "离子注入与退火：如何把杂质「打」进硅里并修复晶格",
    ]},
    {"no": 9, "title": "芯片设计流程：从 RTL 到版图", "phase": "制造与设计", "points": [
        "芯片设计的大致流水线：需求 → 架构 → 逻辑设计 → 物理实现",
        "RTL：用硬件描述语言（Verilog/VHDL）描述电路行为",
        "综合：把 RTL 转成门级网表",
        "布局布线（Place & Route）与版图（layout）是什么",
    ]},
    {"no": 10, "title": "EDA：芯片设计背后的「工业软件」", "phase": "制造与设计", "points": [
        "EDA（电子设计自动化）是什么，为什么芯片设计离不开它",
        "设计验证、综合、仿真、物理验证等关键工具环节",
        "EDA 巨头格局与国产 EDA 的追赶",
        "先进制程为什么让 EDA 越来越复杂、越来越贵",
    ]},

    # —— 第四阶段：芯片与应用 ——
    {"no": 11, "title": "芯片架构：CPU、GPU、SoC 与 NPU 各干什么", "phase": "芯片与应用", "points": [
        "CPU：通用计算的大脑，擅长复杂顺序逻辑",
        "GPU：大规模并行计算，图形与 AI 训练的核心",
        "SoC：把 CPU/GPU/基带/ISP 等集成到一颗芯片",
        "NPU：专门为神经网络推理设计的加速单元",
    ]},
    {"no": 12, "title": "封装与测试：Chiplet 与 3D 封装", "phase": "芯片与应用", "points": [
        "封装是「给芯片穿衣服」：保护、供电、散热与连接",
        "传统封装 vs 先进封装（2.5D/3D）的区别",
        "Chiplet：把大芯片拆成小芯片再拼装，为什么流行",
        "测试在量产中的地位：良率、分 bin 与可靠性",
    ]},
    {"no": 13, "title": "摩尔定律与先进制程：为什么越来越难", "phase": "芯片与应用", "points": [
        "摩尔定律到底说了什么（晶体管密度翻倍的节奏）",
        "制程节点的「nm」在今天更多是营销口径而非真实尺寸",
        "先进制程为什么变慢、变贵（物理极限、成本、良率）",
        "后摩尔时代的路径：先进封装、新材料、架构创新",
    ]},

    # —— 第五阶段：产业格局 ——
    {"no": 14, "title": "产业链全景：设计、制造、封测与设备材料", "phase": "产业格局", "points": [
        "Fabless、Foundry、IDM 三种商业模式的区别",
        "产业链上下游：设计 → 制造 → 封测 → 设备与材料",
        "光刻机、EDA、IP 等关键环节的卡点在哪",
        "一颗芯片从设计到量产的完整旅程复盘",
    ]},
    {"no": 15, "title": "全球格局与国产替代", "phase": "产业格局", "points": [
        "全球半导体产业的地理分工与几大玩家",
        "国产替代的主要环节：设计、制造、设备、材料、EDA",
        "供应链安全与地缘因素对产业的长期影响",
        "面向普通读者的判断：机遇、差距与时间尺度",
    ]},
]

# ---------------------------------------------------------------------------
# 数据源（芯片/半导体行业，用于每期「新闻实例」的真实抓取）
# ---------------------------------------------------------------------------
CATEGORY_MAX_ITEMS = {
    "Chip_News": 5,
}

MODULE_FEEDS = {
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


# ---------------------------------------------------------------------------
# 进度状态（跨 git pull 保留，文件已加入 .gitignore）
# ---------------------------------------------------------------------------
def load_state() -> dict:
    """读取进度状态；文件不存在或损坏时返回默认状态。"""
    default = {"current_lesson": 1, "last_sent_date": None, "last_sent_lesson": None}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        if not isinstance(state, dict):
            return default
        current = state.get("current_lesson")
        if not isinstance(current, int) or not (1 <= current <= len(LESSONS)):
            state["current_lesson"] = 1
        return state
    except FileNotFoundError:
        return default
    except (json.JSONDecodeError, OSError) as e:
        print(f"⚠️ 读取进度文件失败，使用默认状态: {e}")
        return default


def save_state(state: dict) -> None:
    """原子写入进度状态，避免写一半损坏。"""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=DATA_DIR, prefix=".chipschool_state.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, STATE_FILE)
        print(f"📅 进度已保存到 {STATE_FILE}")
    except OSError as e:
        print(f"⚠️ 保存进度失败: {e}")


# ---------------------------------------------------------------------------
# 1. 抓取芯片新闻源
# ---------------------------------------------------------------------------
def fetch_all_feeds():
    """并发抓取芯片/半导体 RSS（7 天时间窗 + 跨源去重），返回 (条目, 统计)。"""
    max_items = CATEGORY_MAX_ITEMS.get("Chip_News", digest.DEFAULT_MAX_ITEMS_PER_SOURCE)
    return digest.collect(MODULE_FEEDS, max_items_per_source=max_items)


# ---------------------------------------------------------------------------
# 2. DeepSeek 生成本讲科普文章
# ---------------------------------------------------------------------------
def generate_briefing(lesson: dict, items: list, stats: dict):
    real_news_context = digest.build_context(items)
    next_lesson = LESSONS[(lesson["no"] % len(LESSONS))]
    points = "\n".join(f"- {p}" for p in lesson["points"])

    print(f"2. 正在通过 DeepSeek 生成本讲科普文章（第 {lesson['no']} 讲）...")
    if not DEEPSEEK_API_KEY:
        print("⚠️ 未配置 DEEPSEEK_API_KEY，改为发送原始条目")
        return None

    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
    exact_iso_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    briefing_prompt = f"""
你是一位严谨、通俗的半导体科普作者，为公众号栏目「芯片通识课」撰写系列文章。
当前时间：{exact_iso_time}。

### 本讲任务
- 第 {lesson['no']} 讲 / 共 {len(LESSONS)} 讲
- 主题：{lesson['title']}
- 所属阶段：{lesson['phase']}
- 必讲知识点（务必全部覆盖，顺序可微调，但不要跑题）：
{points}

================【本周真实抓取到的半导体新闻】================
{real_news_context}
==============================================================

### 输出格式（纯 Markdown，直接输出正文，不要代码围栏）
# 第 {lesson['no']} 讲 · {lesson['title']}

> 阶段：{lesson['phase']} ｜ 系列第 {lesson['no']}/{len(LESSONS)} 讲

## 本讲导语
（2–3 句，用一个生活化类比引出本讲要解决的问题，抓住普通读者）

## 核心知识讲解
（用 `###` 分 2–4 个小节，由浅入深把必讲知识点讲透；多用类比和画面感）

## 本周半导体新闻解读
（从上方【真实抓取到的半导体新闻】中挑 1–2 条最相关的真实新闻：
每条先用一句话转述新闻事实，再用本讲知识解释「这条新闻为什么重要、和本讲有什么关系」，
最后以 `[文章标题](原始链接)` 收尾。挑不出强相关时，选 1–2 条真实半导体新闻，
并诚实说明「与本讲直接关联不强，作为本周产业动态供了解」）

## 一图记 · 关键要点
（3–5 条要点，方便读者收藏复习，可用加粗短句）

## 下期预告
（一句话引出下一讲：{next_lesson['no']} · {next_lesson['title']}）

### 知识部分铁律（防幻觉，优先级最高）
- 只讲公认的教科书级基础（能带、掺杂、PN 结、光刻、CMOS 等学科共识），这是允许讲解的。
- 严禁编造具体数字、年代、公司内部数据、市场份额、具体产品参数；确需举例时用「例如、约、一般」等模糊表达。
- 拿不准的地方必须标注「一般认为 / 通常 / 大致」，不得写成确定事实。
- 知识部分不要加任何外部链接；只有「新闻解读」部分允许出现链接，且必须逐字取自上方真实新闻上下文。

### 新闻部分铁律
- 新闻事实、标题、链接必须逐字来自【本周真实抓取到的半导体新闻】，严禁调用训练记忆补写新闻。
- 每条新闻的链接文字必须使用该条新闻的【标题】，格式 `[标题](原始链接)`；标题中的 `[`、`]`、`(`、`)`、`"` 等会破坏 Markdown 的字符要去掉。
- 若某条新闻在上下文中没有标题或链接，直接整条剔除，严禁凭记忆补链接。

### 风格要求
- 面向公众号普通读者：通俗、具体、有画面感，多用生活类比；避免教科书腔、公式堆砌和纯术语罗列。
- 篇幅适中：核心知识 1200–2000 字为宜；质量优先，宁短勿空，不要注水。
- 所有链接必须逐字取自【真实抓取到的半导体新闻】，缺链接或对不上则整条剔除。
"""

    try:
        briefing_response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": "你是严谨通俗的半导体科普作者。知识部分只讲教科书级共识，新闻部分只引用真实抓取上下文，绝不编造数字、事件或链接。"},
                {"role": "user", "content": briefing_prompt},
            ],
            temperature=0.0,
            stream=False,
        )

        md_content = briefing_response.choices[0].message.content.strip()
        if md_content.startswith("```markdown"):
            md_content = md_content[11:]
        elif md_content.startswith("```"):
            md_content = md_content[3:]
        if md_content.endswith("```"):
            md_content = md_content[:-3]

        print("✅ 本讲科普文章生成成功！")
        return md_content.strip()
    except Exception as e:
        print(f"⚠️ DeepSeek 生成失败: {e}，改为发送原始条目")
        return None


# ---------------------------------------------------------------------------
# 3. 兜底 / 备份 / 渲染 / 发送
# ---------------------------------------------------------------------------
def fallback_markdown(lesson: dict, items: list, stats: dict) -> str:
    """DeepSeek 不可用时也照常发信：附上本讲提纲 + 本期扫描到的原始新闻条目。"""
    points = "\n".join(f"- {p}" for p in lesson["points"])
    return (
        f"# 第 {lesson['no']} 讲 · {lesson['title']}\n\n"
        f"> 阶段：{lesson['phase']} ｜ 系列第 {lesson['no']}/{len(LESSONS)} 讲\n\n"
        "> 未配置 DEEPSEEK_API_KEY 或模型返回空内容，以下为本讲提纲与本期扫描到的原始新闻，供参考。\n\n"
        f"## 本讲必讲知识点\n\n{points}\n\n"
        + digest.items_to_markdown(items, title="本期扫描到的芯片新闻")
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="芯片通识课：半导体基础科普系列（每周五自动下一讲，也可指定讲次）"
    )
    parser.add_argument("--lesson", type=int, default=None,
                        help="强制生成并发送指定讲次（1–15），不修改进度")
    parser.add_argument("--force", action="store_true",
                        help="忽略「仅周五」和「当天已发」检查，跑当前讲次并推进到下一讲")
    parser.add_argument("--dry-run", action="store_true",
                        help="只生成并落盘备份，不发邮件、不推进进度（公众号发布前预览用）")
    args = parser.parse_args(argv)

    date_str = datetime.now().strftime("%Y-%m-%d")
    today = datetime.now().date()
    is_friday = today.weekday() == 4  # Monday=0 ... Friday=4

    state = load_state()
    current = state.get("current_lesson", 1)

    # —— 决定本讲讲次、是否推进进度 ——
    if args.lesson is not None:
        lesson_no = args.lesson
        advance = False
        mode = f"指定讲次 {lesson_no}"
    else:
        lesson_no = current
        if not args.force:
            if state.get("last_sent_date") == date_str:
                print(f"⏭ 今天（{date_str}）已发送过第 {current} 讲，跳过")
                print("   如需重发：python scripts/chipschool_push.py --lesson N（不推进）")
                return 0
            if not is_friday:
                print(f"⏭ 今天不是周五（weekday={today.weekday()}），按计划跳过")
                print("   如需立即跑：--lesson N 指定讲次，或 --force 强制跑当前讲并推进")
                return 0
        advance = not args.dry_run
        mode = "强制" if args.force else "本周自动"

    if not (1 <= lesson_no <= len(LESSONS)):
        print(f"❌ 讲次 {lesson_no} 超出范围：1–{len(LESSONS)}")
        return 2
    lesson = LESSONS[lesson_no - 1]

    print(f"===== 芯片通识课（{mode}）：第 {lesson['no']} 讲 · {lesson['title']} =====")

    items, stats = fetch_all_feeds()

    md_content = generate_briefing(lesson, items, stats)
    if not md_content:
        print("⚠️ 未生成 AI 文章，改为发送提纲 + 原始条目")
        md_content = fallback_markdown(lesson, items, stats)

    md_content, safety = digest.validate_briefing(md_content, items)
    if safety["hallucinated"]:
        print(f"🛡️ 防幻觉校验：{safety['ok_links']}/{safety['total_links']} 个链接通过，"
              f"移除 {safety['hallucinated']} 个不可信链接")
        for _text, url in safety["removed"]:
            print(f"   ↳ 已移除: {url}")
        md_content += digest.hallucination_notice(safety)

    backup_path = os.path.join(BACKUP_DIR, f"{FLOW_NAME}_L{lesson_no:02d}_{date_str}.md")
    digest.save_backup(md_content, date_str, backup_path)

    if args.dry_run:
        print(f"🔍 dry-run：文章已生成并落盘 {backup_path}，未发邮件、未推进进度")
        return 0

    html, plain_text = digest.render_email(
        brand_title=BRAND_TITLE, subtitle=SUBTITLE, footer=FOOTER,
        markdown_text=md_content, stats=stats, date_str=date_str,
    )
    ok = digest.send_email(
        f"{SUBJECT} · 第 {lesson['no']} 讲 {lesson['title']} ({date_str})",
        html, plain_text,
        attachments=[(f"{FLOW_NAME}-L{lesson_no:02d}-{date_str}-items.md",
                      digest.items_to_markdown(items))],
    )
    if not ok:
        return 1

    if advance:
        next_no = lesson_no + 1
        if next_no > len(LESSONS):
            next_no = 1
            print("🔁 15 讲已全部发布完一轮，进度回到第 1 讲")
        state["current_lesson"] = next_no
        state["last_sent_date"] = date_str
        state["last_sent_lesson"] = lesson_no
        save_state(state)
        print(f"📅 已推进：下一讲 = 第 {next_no} 讲")
    else:
        print("ℹ️ 指定讲次模式：进度未修改")
    return 0


if __name__ == "__main__":
    sys.exit(main())
