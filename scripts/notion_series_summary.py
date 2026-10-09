#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 Notion 知识库中的「系列」总结成一篇导览文章（更易懂版），写回 Notion。

每个系列一篇总结，作为该系列的「第 0 讲」导览（序号=0），
排序在详细讲次之前，方便按顺序学习。

用法：
    export NOTION_API_SECRET=ntn_...
    python scripts/notion_series_summary.py --database-id <id> [--dry-run]

内容来源：基于系列内各讲真实内容的提炼 + 通俗化改写，不编造技术细节。
"""

import argparse
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wechat_notion import (_notion_headers, _get_database_schema, _adapt_properties,
                           _rich_text)  # noqa: E402


# ---------------------------------------------------------------------------
# 7 篇系列总结（标题 / 一句话摘要 / 分节内容 / 学习路径）
# ---------------------------------------------------------------------------
SERIES_SUMMARIES = [
    {
        "series": "CCIX",
        "category": "互连与总线",
        "title": "📚 系列总结 · CCIX：让 CPU 和加速器共享一块内存",
        "summary": "CCIX 是基于 PCIe 物理层的缓存一致性互连，让 CPU 与加速器像共享同一块内存一样协同工作。",
        "sections": [
            ("一句话理解", "把 CPU 和加速器比作两个办公室：传统 PCIe 下，两个办公室要交换文件，得靠专人来回送（驱动 + DMA 搬运数据）；CCIX 让它们共用同一块白板，谁写了什么大家立刻同步看到，省掉了搬运的麻烦。"),
            ("为什么需要 CCIX", [
                "传统 PCIe 加速器要共享数据，得靠软件/驱动显式地读出、写入、再同步，有额外延迟和开销。",
                "CCIX 用「缓存一致性」自动保证 CPU 与加速器的缓存里是同一份最新数据。",
                "因为复用了 PCIe 的物理层，CCIX 实现门槛低，最高链路速率 25 GT/s，还支持端口聚合提升带宽。",
            ]),
            ("核心概念", [
                "缓存一致性：多个芯片各自有缓存，协议自动维护数据一致，上层像访问本地内存一样简单。",
                "分层结构：CCIX 协议层（一致性协议）+ CCIX 链路层，底层基本复用 PCIe 事务层/数据链路层/物理层。",
                "四类代理：RA 请求代理、HA 主代理、SA 从代理、EA 错误代理，用代理 ID 标识。",
                "共享虚拟内存 SVM：加速器直接引用主机的虚拟地址，数据无缝共享。",
            ]),
            ("学习路径（9 讲）", [
                "第 1 讲：CCIX 是什么、分层结构、拓扑、代理模型。",
                "第 2 讲：PCI/PCIe 背景回顾 + 关键术语 + 共享虚拟内存。",
                "第 3–8 讲：缓存一致性协议、事务与报文、寄存器/DVSEC 细节。",
                "第 9 讲：RAS 错误处理 + 地址翻译服务 ATS。",
            ]),
            ("延伸", "CCIX 联盟后来与 Gen-Z 等标准合并演化，CXL 成为事实上的主流标准。学完 CCIX 再学 CXL，很多缓存一致性的思想是相通的。"),
        ],
    },
    {
        "series": "CXL",
        "category": "互连与总线",
        "title": "📚 系列总结 · CXL：把内存从 CPU 里「解耦」出来",
        "summary": "CXL 是 Intel 2019 年提出的开放互连标准，让 CPU 能高效外接扩展内存、持久内存和加速器。",
        "sections": [
            ("一句话理解", "过去内存是 CPU 的私有财产，焊死在一起、容量固定。CXL 把内存变成可以外接、可以多台机器共享、按需租用的资源——就像从「自己买地盖仓库」变成「按需租云仓库」。"),
            ("三个协议（三根管道）", [
                "CXL.io：负责设备的发现、枚举、配置，本质上基本就是 PCIe，是非一致 I/O。",
                "CXL.cache：让加速器去缓存主机内存（设备一侧缓存主机数据）。",
                "CXL.mem：让主机 CPU 直接访问设备上的内存（内存扩展的关键）。",
            ]),
            ("三种设备类型", [
                "Type 1：只有 CXL.cache + CXL.io，无自带内存的加速器（如智能网卡）。",
                "Type 2：三种协议都有，自带内存的加速器（如 GPU）。",
                "Type 3：只有 CXL.mem + CXL.io，纯内存扩展设备（内存条/内存池）。",
            ]),
            ("分层结构", [
                "事务层：CXL.io / CXL.cache / CXL.mem 三种协议报文。",
                "链路层：负责可靠传输。",
                "ARB/MUX：把多个协议的数据动态复用/仲裁到一条物理链路上。",
                "Flex Bus 物理层：在 PCIe 物理层基础上扩展，承载 CXL 的 flit 数据。",
            ]),
            ("学习路径（12 讲）", [
                "第 1 讲：CXL 是什么、历史与版本（1.0/1.1/2.0/3.0）。",
                "第 2 讲：系统架构与三种设备类型。",
                "第 3–5 讲：CXL.io / CXL.cache / CXL.mem 事务层。",
                "第 6 讲：链路层。",
                "第 7 讲：ARB/MUX 多路复用。",
                "第 8 讲：Flex Bus 物理层。",
                "第 9 讲：寄存器、复位与初始化。",
                "第 10 讲：电源管理。",
                "第 11 讲：安全（加密）。",
                "第 12 讲：Pond 论文——CXL 内存池化在云端的落地。",
            ]),
            ("为什么重要", "CXL 是「内存池化」和「内存扩展」的主流路线，正在改变数据中心如何分配内存资源，也是国产芯片和服务器厂商重点跟进的方向。"),
        ],
    },
    {
        "series": "PCIe",
        "category": "互连与总线",
        "title": "📚 系列总结 · PCIe：电脑内部的「高速专线」",
        "summary": "PCIe 是连接 CPU 与显卡、SSD、网卡等设备的主流高速串行总线。",
        "sections": [
            ("一句话理解", "PCIe 把早期 PCI 的「共享乡间小路」改成了「每户独享的高速专线」：串行、点对点、每个设备独享带宽，不再互相争抢。"),
            ("核心概念", [
                "演进：PCI（并行、共享总线，132 MB/s）→ PCIe（串行、点对点，每设备独享带宽）。",
                "Lane：每条 lane 是一对差分信号，速率逐代翻倍：Gen3 8 GT/s、Gen4 16 GT/s、Gen5 32 GT/s、Gen6 64 GT/s。",
                "拓扑：Root Complex（根复合体）→ Switch（交换）→ Endpoint（端点）。",
                "分层：事务层（TLP）→ 数据链路层（DLLP）→ 物理层。",
                "配置空间：每个 Function 有 4K 配置空间，能力寄存器以链表组织（含扩展能力 DVSEC）。",
            ]),
            ("高级特性", [
                "LTR（延迟容忍报告）：设备主动告诉系统「我能容忍多大延迟」，帮助 CPU 优化功耗。",
                "OBFF（优化缓冲刷新/填充）：协调设备何时刷新缓冲，改善功耗与延迟。",
                "电源管理：ASPM、L0s/L1/L2 等低功耗状态。",
            ]),
            ("学习路径（12 讲）", [
                "第 1–3 讲：PCIe 基础、拓扑、配置空间。",
                "第 4–10 讲：事务层、链路层、物理层、电源管理等协议细节。",
                "第 11 讲：LTR 延迟容忍报告。",
                "第 12 讲：OBFF 优化缓冲刷新/填充。",
            ]),
            ("提示", "PCIe 是理解 CCIX/CXL/UCIe 的底座——后三者都在 PCIe 的基础上做了扩展或复用，先把 PCIe 基础打牢，后面会轻松很多。"),
        ],
    },
    {
        "series": "UCIe",
        "category": "互连与总线",
        "title": "📚 系列总结 · UCIe：让「小芯片」能像乐高一样拼接",
        "summary": "UCIe 是 2022 年推出的 Chiplet（芯粒）互连标准，定义芯片内部不同小芯片之间怎么高速互联。",
        "sections": [
            ("一句话理解", "把一颗大芯片拆成多颗小芯片（芯粒），各自用最合适的工艺制造，再封装拼在一起。UCIe 就是这些小芯片之间的「标准卡扣」，让不同厂家、不同工艺的芯粒能拼装。"),
            ("为什么需要 Chiplet", [
                "先进制程越来越贵、良率难做，把大芯片拆小可以分别用最优工艺、复用成熟模块。",
                "UCIe 统一了 die-to-die（D2D）互连接口，避免每家各搞一套私有协议。",
            ]),
            ("核心概念", [
                "适用范围：芯片内部、封装内部的裸片到裸片互连（距离短、速率极高）。",
                "两种物理接口：标准封装（2D，基板走线）与先进封装（2.5D/3D，硅中介层，速率更高）。",
                "协议层：可复用 PCIe/CXL 协议（流模式），也可用原生流协议。",
                "Flit 模式 vs Raw 模式：是否带流控/校验的两种传输格式。",
                "Sideband 边带链路：负责链路训练、管理、寄存器访问。",
                "RDI（原始裸片互连）与 FDI（流感知裸片互连）两种接口。",
            ]),
            ("学习路径（10 讲）", [
                "第 1–2 讲：UCIe 是什么、整体架构。",
                "第 3–6 讲：物理层、适配层、协议层。",
                "第 7 讲：Sideband 边带链路。",
                "第 8 讲：系统架构与可管理性。",
                "第 9 讲：配置参数与软件视图。",
                "第 10 讲：RDI/FDI 接口定义。",
            ]),
            ("提示", "UCIe 与 CXL 关系密切：UCIe 的协议层能承载 CXL/PCIe 协议，相当于把 CXL 从「芯片之间」拉近到了「芯片内部」。"),
        ],
    },
    {
        "series": "CS61C·RISC-V",
        "category": "计算机体系结构",
        "title": "📚 系列总结 · CS61C：用 RISC-V 从零看懂 CPU",
        "summary": "基于 UC Berkeley 经典课 CS61C，用开源指令集 RISC-V 讲透 CPU 如何工作。",
        "sections": [
            ("一句话理解", "像搭积木一样，从一条最简单的算术指令开始，逐步加模块、加控制信号，最终拼出一个能真正跑程序的 CPU。"),
            ("核心概念", [
                "RISC-V：开源指令集架构（ISA），RV32I 是基础 32 位整数指令集。",
                "数据路径（Datapath）：单周期 CPU 执行一条指令的流程——取指、译码、执行、访存、写回。",
                "指令类型：I-Type / S-Type / B-Type / J-Type / U-Type 各有不同的编码与用途。",
                "过程调用：函数调用背后的 ABI 约定——寄存器如何保存、栈如何管理、返回地址放哪。",
            ]),
            ("学习路径（4 讲）", [
                "L12：RISC-V 过程调用（函数调用背后的性能与架构权衡）。",
                "L20：数据路径 I（先搭最基础的数据通路）。",
                "L21：数据路径 II（逐步扩展出完整单周期数据路径）。",
                "L23：如何构造一个 RISC-V CPU（从零实现 RV32I）。",
            ]),
            ("提示", "这 4 篇来自 CS61C 的散讲，建议按 L12 → L20 → L21 → L23 的顺序看，先懂「函数调用」，再懂「数据通路」，最后「拼出 CPU」。"),
        ],
    },
    {
        "series": "CS336·MoE",
        "category": "大模型与推理",
        "title": "📚 系列总结 · MoE：大模型里的「分诊台」架构",
        "summary": "混合专家模型（MoE）把大模型拆成多个专家，每次只激活一小部分，是 Mistral、DeepSeek、GPT-4 背后的关键技术。",
        "sections": [
            ("一句话理解", "把大模型比作一座大医院：MoE 设一个「分诊台」（门控网络），每个病人（token）只被分到最相关的几个科室（专家）就诊，而不是每个科室都跑一遍，省下大量算力。"),
            ("为什么需要 MoE", [
                "单纯堆参数、堆算力越来越贵，需要更高效的扩展方式。",
                "MoE 在总参数量很大的同时，每次推理只激活少数专家，性价比更高。",
            ]),
            ("核心概念", [
                "专家（Expert）：一组独立的网络子模块。",
                "门控/路由（Gating/Router）：决定每个 token 该送给哪些专家、权重多少。",
                "稀疏激活：每次只激活 Top-k 个专家，而非全部。",
                "训练难点：负载均衡、专家坍缩、路由不稳定等。",
            ]),
            ("学习路径（2 讲）", [
                "Part 1：MoE 的原理与结构。",
                "Part 2：如何训练 MoE（训练挑战与解决方案）。",
            ]),
            ("提示", "结合本知识库里的 DeepSeek、vLLM、KV Cache 等文章一起看，能把「模型架构 → 推理加速」串成一条完整线索。"),
        ],
    },
    {
        "series": "内存异构分层",
        "category": "存储与内存",
        "title": "📚 系列总结 · 内存异构分层：Agentic AI 时代的「以内存为中心」计算",
        "summary": "探讨 Agentic AI 时代下，内存为中心的异构分层：从 HBM/DDR 到 CXL 扩展内存，再到 SSD 的多层存储。",
        "sections": [
            ("说明", "该系列原文为视频课程，Notion 中只保留了标题与链接，视频内容未转成文字。以下为基于主题的要点梳理，帮助定位这组内容。"),
            ("核心主题", [
                "内存异构分层：把内存按「带宽-容量-延迟-成本」分成多层（HBM、DDR、CXL 扩展内存、SSD 等）。",
                "以内存为中心的计算：数据量暴涨，内存（而非 CPU）成为瓶颈，架构设计围绕「把数据尽量靠近计算」展开。",
                "Agentic AI：智能体应用让数据访问模式更随机、对内存延迟更敏感，进一步推动内存体系重构。",
            ]),
            ("学习路径（2 讲）", [
                "第 2 部分：内存异构分层（上）。",
                "第 3 部分：内存异构分层（下）。",
            ]),
            ("提示", "配合本知识库「存储与内存」分类下的 HBM、CXL 内存池化、存算一体等文章一起看，能把内存体系串起来。"),
        ],
    },
]


# ---------------------------------------------------------------------------
# 渲染与推送
# ---------------------------------------------------------------------------
def render_blocks(summary: dict) -> list:
    """把 summary 结构渲染成 Notion 块列表。"""
    blocks = []
    # 顶部元信息 callout
    meta = (
        f"分类：{summary['category']}\n"
        f"系列：{summary['series']} ｜ 导览（第 0 讲）\n"
        f"公众号：AI 系列总结\n"
        f"摘要：{summary['summary']}"
    )
    blocks.append({"object": "block", "type": "callout",
                   "callout": {"rich_text": [_rich_text(meta)], "icon": {"type": "emoji", "emoji": "📚"}}})

    # 导语
    blocks.append({"object": "block", "type": "heading_2",
                   "heading_2": {"rich_text": [_rich_text("导读")]}})
    blocks.append({"object": "block", "type": "paragraph",
                   "paragraph": {"rich_text": [_rich_text(summary["summary"])]}})

    for heading, content in summary["sections"]:
        blocks.append({"object": "block", "type": "heading_2",
                       "heading_2": {"rich_text": [_rich_text(heading)]}})
        if isinstance(content, str):
            blocks.append({"object": "block", "type": "paragraph",
                           "paragraph": {"rich_text": [_rich_text(content)]}})
        else:  # list of bullet points
            for item in content:
                blocks.append({"object": "block", "type": "bulleted_list_item",
                               "bulleted_list_item": {"rich_text": [_rich_text(item)]}})
    return blocks


def push_summaries(database_id: str, token: str, dry_run: bool = False) -> dict:
    base = "https://api.notion.com/v1"
    schema = _get_database_schema(database_id, token)
    stats = {"pushed": 0, "failed": 0, "skipped": 0}

    # 先取已有页面，按「系列」去重（避免重复生成导览）
    existing_series = set()
    cursor = None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        r = requests.post(f"{base}/databases/{database_id}/query",
                          headers=_notion_headers(token), json=body, timeout=60)
        if r.status_code != 200:
            break
        j = r.json()
        for pg in j.get("results", []):
            s = (pg.get("properties", {}).get("系列", {}).get("select") or {}).get("name")
            seq = pg.get("properties", {}).get("序号", {}).get("number")
            if s and seq == 0:
                existing_series.add(s)
        if not j.get("has_more"):
            break
        cursor = j.get("next_cursor")

    for summary in SERIES_SUMMARIES:
        if summary["series"] in existing_series:
            stats["skipped"] += 1
            print(f"⏭  {summary['series']} 导览已存在，跳过")
            continue
        article = {
            "title": summary["title"],
            "author": "AI 系列总结",
            "published": "",
            "url": "",
            "category": summary["category"],
            "series": summary["series"],
            "seq": 0,
            "summary": summary["summary"],
        }
        props, _ = _adapt_properties(schema, article)
        children = render_blocks(summary)
        body = {"parent": {"database_id": database_id}, "properties": props, "children": children[:90]}
        if dry_run:
            print(f"[dry-run] {summary['series']} → {summary['title'][:40]} | {len(children)} blocks")
            stats["pushed"] += 1
            continue
        r = requests.post(f"{base}/pages", headers=_notion_headers(token), json=body, timeout=60)
        if r.status_code not in (200, 201):
            print(f"   ❌ {summary['series']} -> {r.status_code} {r.text[:200]}")
            stats["failed"] += 1
            continue
        page_id = r.json()["id"]
        for extra in [children[i:i + 90] for i in range(90, len(children), 90)]:
            requests.patch(f"{base}/blocks/{page_id}/children",
                           headers=_notion_headers(token), json={"children": extra}, timeout=60)
        print(f"   ✓ {summary['series']} 导览已写入 | {len(children)} blocks")
        stats["pushed"] += 1
        time.sleep(0.4)

    print(f"\n✅ 系列总结完成：新增 {stats['pushed']}，跳过已有 {stats['skipped']}，失败 {stats['failed']}")
    return stats


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="把每个系列总结成一篇导览文章，写入 Notion")
    p.add_argument("--database-id", default=os.environ.get("NOTION_DATABASE_ID", ""))
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    token = os.environ.get("NOTION_API_SECRET", "").strip()
    if not token:
        print("❌ 缺少 NOTION_API_SECRET")
        return 1
    db = args.database_id.strip()
    if not db:
        print("❌ 缺少 --database-id 或 NOTION_DATABASE_ID")
        return 1
    push_summaries(db, token, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
