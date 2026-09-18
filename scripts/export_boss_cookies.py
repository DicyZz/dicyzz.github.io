#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地辅助脚本：登录 BOSS 直聘后导出 Cookie。

用法（本地有显示器时运行）：
    python scripts/export_boss_cookies.py

运行后会打开浏览器，请扫码/验证码登录 BOSS 直聘（找岗位页面）。
登录成功后脚本会把 Cookie 保存到 data/boss_cookies.json，
并把可直接粘贴到 GitHub Secrets 的 JSON 也打印到控制台。
"""

import json
import os
from playwright.sync_api import sync_playwright

SEARCH_URL = "https://www.zhipin.com/web/geek/job?query=ESL&city=101010100"
OUT_FILE = "data/boss_cookies.json"


def main():
    os.makedirs("data", exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()
        page.goto(SEARCH_URL, timeout=45000)

        print("请在浏览器中登录 BOSS 直聘（扫码或验证码）。")
        print("登录成功后，页面应显示岗位列表；确认后回到终端按回车继续。")
        input("按回车导出 Cookie...")

        cookies = context.cookies()
        with open(OUT_FILE, "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)

        print(f"\n✅ Cookie 已保存到 {OUT_FILE}，共 {len(cookies)} 条")
        print("\n---------- 复制以下内容到 GitHub Secrets (BOSS_COOKIES) ----------")
        print(json.dumps(cookies, ensure_ascii=False))
        print("------------------------------------------------------------------")
        browser.close()


if __name__ == "__main__":
    main()
