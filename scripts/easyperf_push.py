import os
import sys
import re
import json
import requests
import markdown
from premailer import transform
from openai import OpenAI

# 读取 Secrets
APP_ID = os.environ.get("WECHAT_APP_ID")
APP_SECRET = os.environ.get("WECHAT_APP_SECRET")
THUMB_MEDIA_ID = os.environ.get("WECHAT_THUMB_MEDIA_ID")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
SCF_PROXY_URL = os.environ.get("SCF_PROXY_URL") # 腾讯云函数 URL

# 1. 调用 DeepSeek 生成 EasyPerf 风格简报
def generate_briefing():
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
    prompt = """
    你是一个专注于计算机体系结构、系统性能优化和 LLM 硬件加速的技术专家。
    请搜集/总结最新的硬件与系统性能动态，并按 EasyPerf 风格生成一篇 Markdown 简报。
    包含三个板块：News 📢、Blog Posts 📝、Research Papers 🎓。
    每条包含：标题、简要技术解读（突出微架构/系统性能机制）、参考来源超链接 [来源名称](URL)。
    """
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )
    return response.choices[0].message.content

# 2. Markdown 转微信 HTML (排版与外链转脚注)
def md_to_wechat_html(md_content):
    links = []
    def replace_link(match):
        text, url = match.group(1), match.group(2)
        links.append(url)
        return f"{text}<sup>[{len(links)}]</sup>"

    md_processed = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', replace_link, md_content)
    if links:
        md_processed += "\n\n---\n**参考文献 / 链接：**\n"
        for idx, url in enumerate(links, 1):
            md_processed += f"[{idx}] {url}\n\n"

    raw_html = markdown.markdown(md_processed, extensions=['tables', 'fenced_code'])
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

# 3. 通过腾讯云 SCF 中转请求微信 API
def get_access_token():
    payload = {"action": "get_token", "appid": APP_ID, "secret": APP_SECRET}
    res = requests.post(SCF_PROXY_URL, json=payload).json()
    res_body = json.loads(res.get("body", "{}"))
    if "access_token" not in res_body:
        raise Exception(f"获取 Token 失败: {res_body}")
    return res_body["access_token"]

def push_to_draft(access_token, html_content):
    payload = {
        "action": "add_draft",
        "token": access_token,
        "payload": {
            "articles": [{
                "title": "【EasyPerf】每日硬件与系统性能动态",
                "author": "DicyZz",
                "digest": "体系结构、微架构优化与 LLM 系统最新动态",
                "content": html_content,
                "thumb_media_id": THUMB_MEDIA_ID
            }]
        }
    }
    res = requests.post(SCF_PROXY_URL, json=payload).json()
    return json.loads(res.get("body", "{}"))

if __name__ == "__main__":
    print("1. 生成简报...")
    md_text = generate_briefing()
    print("2. 转换 HTML...")
    html_text = md_to_wechat_html(md_text)
    print("3. 发送草稿...")
    token = get_access_token()
    result = push_to_draft(token, html_text)
    
    if result.get("errcode") == 0:
        print("✅ 成功存入微信草稿箱！")
    else:
        print(f"❌ 推送失败: {result}")
        sys.exit(1)
