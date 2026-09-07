import os
import sys
import re
import json
import requests
import markdown
from premailer import transform
from openai import OpenAI

# 环境变量读取
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("LLM_API_KEY")
SCF_PROXY_URL = os.environ.get("SCF_PROXY_URL")
WECHAT_APP_ID = os.environ.get("WECHAT_APP_ID")
WECHAT_APP_SECRET = os.environ.get("WECHAT_APP_SECRET")
WECHAT_THUMB_MEDIA_ID = os.environ.get("WECHAT_THUMB_MEDIA_ID")

def generate_briefing():
    print("1. 正在生成 EasyPerf 简报...")
    if not DEEPSEEK_API_KEY:
        print("❌ 错误：未配置 DEEPSEEK_API_KEY，请检查 GitHub Secrets！")
        sys.exit(1)

    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
    prompt = """
    你是一个专注于计算机体系结构、系统性能优化和 LLM 硬件加速的技术专家。
    请搜集/总结最新的硬件与系统性能动态，按 EasyPerf 风格生成一篇 Markdown 简报。
    包含三个板块：
    1. News 📢
    2. Blog Posts 📝
    3. Research Papers 🎓
    每条内容包含：标题、简要技术解读（突出微架构/系统性能机制）、参考来源超链接 [来源名称](URL)。
    """
    res = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )
    print("✅ 简报生成成功！")
    return res.choices[0].message.content

def md_to_wechat_html(md_content):
    print("2. 正在转换 Markdown 为微信公众号专属 HTML 排版...")
    links = []
    def replace_link(match):
        text, url = match.group(1), match.group(2)
        links.append(url)
        return f"{text}<sup>[{len(links)}]</sup>"

    # 将 Markdown 外链转换为微信脚注模式
    md_processed = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', replace_link, md_content)
    if links:
        md_processed += "\n\n---\n**参考文献 / 链接：**\n"
        for idx, url in enumerate(links, 1):
            md_processed += f"[{idx}] {url}\n\n"

    raw_html = markdown.markdown(md_processed, extensions=['tables', 'fenced_code'])
    
    # 内联样式（解决微信排版兼容性问题）
    css_style = """
    <style>
        h3 { font-size: 16px; font-weight: bold; color: #1a1a1a; border-left: 4px solid #07c160; padding-left: 8px; margin-top: 18px; margin-bottom: 10px; }
        p, li { font-size: 14px; color: #333333; line-height: 1.75; margin-bottom: 8px; }
        ul { padding-left: 18px; }
        strong { color: #07c160; font-weight: bold; }
        code { background: #f6f8fa; padding: 2px 4px; border-radius: 3px; color: #d73a49; font-size: 13px; }
        sup { color: #576b95; font-weight: bold; padding: 0 2px; }
        hr { border: none; border-top: 1px solid #eee; margin: 20px 0; }
    </style>
    """
    return transform(f"<html><head>{css_style}</head><body>{raw_html}</body></html>")

def get_access_token():
    print("3. 正在通过 SCF 代理获取微信 Access Token...")
    if not SCF_PROXY_URL:
        print("❌ 错误：未配置 SCF_PROXY_URL！")
        sys.exit(1)

    payload = {"action": "get_token", "appid": WECHAT_APP_ID, "secret": WECHAT_APP_SECRET}
    resp = requests.post(SCF_PROXY_URL, json=payload, timeout=30)
    
    try:
        res_data = resp.json()
        body_content = json.loads(res_data["body"]) if isinstance(res_data.get("body"), str) else res_data.get("body", res_data)
    except Exception as e:
        print(f"❌ 解析 SCF 返回数据失败: {resp.text}")
        sys.exit(1)

    if "access_token" not in body_content:
        print(f"❌ 获取 Access Token 失败，微信返回: {body_content}")
        sys.exit(1)
        
    print("✅ Access Token 获取成功！")
    return body_content["access_token"]

def push_to_draft(access_token, html_content):
    print("4. 正在通过 SCF 推送文章到微信草稿箱...")
    payload = {
        "action": "add_draft",
        "token": access_token,
        "payload": {
            "articles": [{
                "title": "【EasyPerf】每日硬件与系统性能动态",
                "author": "DicyZz",
                "digest": "体系结构、微架构优化与 LLM 系统最新动态",
                "content": html_content,
                "thumb_media_id": WECHAT_THUMB_MEDIA_ID
            }]
        }
    }
    resp = requests.post(SCF_PROXY_URL, json=payload, timeout=30)
    
    try:
        res_data = resp.json()
        body_content = json.loads(res_data["body"]) if isinstance(res_data.get("body"), str) else res_data.get("body", res_data)
    except Exception as e:
        print(f"❌ 解析 SCF 推送返回数据失败: {resp.text}")
        sys.exit(1)

    if body_content.get("errcode") == 0 or "media_id" in body_content:
        print("🎉 成功存入微信公众号草稿箱！")
        print(f"草稿 Media ID: {body_content.get('media_id')}")
    else:
        print(f"❌ 存入草稿箱失败，微信返回错误: {body_content}")
        sys.exit(1)

if __name__ == "__main__":
    md_text = generate_briefing()
    html_text = md_to_wechat_html(md_text)
    token = get_access_token()
    push_to_draft(token, html_text)
