#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对本地 Notion 知识库提问：检索相关文章 → 用 DeepSeek 总结（带引用来源）。

先运行 scripts/notion_export.py 生成 knowledge_base/notion/，然后：

    export DEEPSEEK_API_KEY=sk-...          # 可选；不配置则只输出检索到的原文片段
    python scripts/ask_kb.py "CXL 和 CCIX 有什么区别？"
    python scripts/ask_kb.py "什么是缓存一致性" --top 6 --no-llm

防幻觉：
    - 只把检索到的资料喂给模型，并要求逐条标注引用标题。
    - 资料里没有的内容要求模型明确说“知识库中未找到”，禁止编造。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

KB_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "knowledge_base", "notion",
)
INDEX_FILE = os.path.join(KB_DIR, "_index.json")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
DEFAULT_TOP = 8
CHUNK_LIMIT = 1400


# ---------------------------------------------------------------------------
# 检索
# ---------------------------------------------------------------------------
# 问句里的常见停用词：它们对“区分主题”没有帮助，还会把结果带偏
_STOP_CHARS = set("的和了是在有个上与或及对中为不这就那吗呢吧啊要请帮把被从到比让给向")
_STOP_BIGRAMS = {
    "区别", "差异", "什么", "如何", "怎么", "为什么", "哪些", "介绍", "讲解",
    "讲一下", "对比", "比较", "之间", "是什么", "什么是", "有无", "有什",
    "异同", "有何", "一下", "请问", "帮我", "总结", "归纳", "梳理", "简述",
}


def _query_terms(q: str) -> list[str]:
    q = (q or "").lower().strip()
    terms: list[str] = []
    terms += re.findall(r"[a-z0-9]+", q)
    # 中文：单字 + 二元组，兼顾“缓存”“缓存一致性”这类表达
    zh = re.sub(r"[^\u4e00-\u9fff]", "", q)
    # 单个汉字噪音太大（如“区/别”），只用英文词 + 中文二元组检索
    for i in range(len(zh) - 1):
        bg = zh[i:i + 2]
        if bg not in _STOP_BIGRAMS:
            terms.append(bg)
    # 去掉纯单数字/单字母噪音，去重保持顺序
    uniq: list[str] = []
    for t in terms:
        if t and t not in uniq and not (len(t) == 1 and t.isascii()):
            uniq.append(t)
    return uniq


def _score(doc: dict, content: str, terms: list[str]) -> float:
    if not terms:
        return 0.0
    title = (doc.get("title") or "").lower()
    series = (doc.get("series") or "").lower()
    category = (doc.get("category") or "").lower()
    summary = (doc.get("summary") or "").lower()
    tags = " ".join(doc.get("tags") or []).lower()
    clow = content.lower()

    def count(hay: str, t: str) -> int:
        return hay.count(t)

    score = 0.0
    for t in terms:
        score += 3.0 * count(title, t)
        score += 2.5 * count(tags, t)
        score += 2.0 * count(summary, t)
        score += 1.5 * count(series, t)
        score += 1.0 * count(category, t)
        c = count(clow, t)
        score += min(c, 8) * 0.35
    # 系列导览（序号=0）通常是很好的入门总览
    if doc.get("seq") == 0:
        score *= 1.08
    return score


def _snippet(content: str, terms: list[str], width: int = 240) -> str:
    low = content.lower()
    pos = -1
    for t in sorted(terms, key=len, reverse=True):
        p = low.find(t)
        if p >= 0:
            pos = p
            break
    if pos < 0:
        return content[:width]
    start = max(0, pos - width // 3)
    return ("…" if start else "") + content[start:start + width].strip() + "…"


def retrieve(question: str, top: int = DEFAULT_TOP, kb_dir: str = KB_DIR) -> list[dict]:
    if not os.path.isfile(INDEX_FILE):
        print(f"❌ 未找到 {INDEX_FILE}，请先运行 scripts/notion_export.py")
        raise SystemExit(2)

    with open(INDEX_FILE, encoding="utf-8") as f:
        index = json.load(f)

    terms = _query_terms(question)
    scored: list[tuple[float, dict, str]] = []
    for doc in index:
        path = os.path.join(kb_dir, doc["file"])
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except OSError:
            continue
        s = _score(doc, content, terms)
        if s > 0:
            scored.append((s, doc, content))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for s, doc, content in scored[:top]:
        results.append({
            "score": round(s, 1),
            "title": doc["title"],
            "series": doc["series"],
            "seq": doc["seq"],
            "file": doc["file"],
            "url": doc["url"],
            "snippet": _snippet(content, terms),
            "content": content,
        })
    return results


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------
def _render_prompt(question: str, results: list[dict]) -> str:
    parts = []
    for i, r in enumerate(results, 1):
        label = r["title"]
        if r["series"]:
            label += f"（{r['series']} 第 {r['seq']} 讲）"
        parts.append(f"\n[资料{i}] {label}\n{r['content'][:CHUNK_LIMIT]}")
    joined = "\n".join(parts)
    return (
        "你是个人知识库助手。请仅依据下面的资料回答用户问题。\n"
        "要求：\n"
        "1. 先给出一段「结论」，再用要点展开；用通俗易懂的中文。\n"
        "2. 每个关键结论后面标注来源，格式如【来源：资料1】。\n"
        "3. 如果资料中没有相关信息，直接说「知识库中未找到相关内容」，不要编造。\n"
        "4. 不要输出资料里没有的数字、年份、人名或技术细节。\n\n"
        f"用户问题：{question}\n\n"
        f"资料：{joined}\n"
    )


def _llm_answer(question: str, results: list[dict]) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
    resp = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[{"role": "user", "content": _render_prompt(question, results)}],
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()


def _plain_answer(question: str, results: list[dict]) -> str:
    lines = [f"问题：{question}", "", "检索到以下相关文章（未配置 DEEPSEEK_API_KEY，仅展示原文片段）："]
    for i, r in enumerate(results, 1):
        lines += ["", f"### {i}. {r['title']}"]
        meta = []
        if r["series"]:
            meta.append(f"系列：{r['series']} 第 {r['seq']} 讲")
        meta.append(f"文件：{r['file']}")
        if r["url"]:
            meta.append(f"链接：{r['url']}")
        lines.append(" ｜ ".join(meta))
        lines.append(f"> {r['snippet']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="对本地 Notion 知识库提问并总结")
    ap.add_argument("question", nargs="+", help="问题")
    ap.add_argument("--top", type=int, default=DEFAULT_TOP)
    ap.add_argument("--kb-dir", default=KB_DIR)
    ap.add_argument("--no-llm", action="store_true", help="跳过 DeepSeek，只输出检索片段")
    args = ap.parse_args(argv)

    question = " ".join(args.question).strip()
    if not question:
        print("请输入问题")
        return 2

    results = retrieve(question, args.top, args.kb_dir)
    if not results:
        print("未找到相关文章。可以先运行 notion_export.py 同步最新知识库。")
        return 1

    print(f"🔎 命中 {len(results)} 篇：", " / ".join(r['title'] for r in results[:5]))
    print("")

    if args.no_llm or not DEEPSEEK_API_KEY:
        print(_plain_answer(question, results))
    else:
        print(_llm_answer(question, results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
