#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从本机 Chrome 导出 BOSS 直聘登录 Cookie。

依赖：pip install cryptography

原理：Chrome 把登录 Cookie 加密保存在本机 SQLite，密钥在 macOS 钥匙串
（"Chrome Safe Storage"）。脚本读取该密钥解密 zhipin.com 的 Cookie，
输出可直接粘贴到 GitHub Secrets (BOSS_COOKIES) 的 JSON。

用法：
    1. 先在 Chrome 里登录 BOSS 直聘（www.zhipin.com 能看到岗位列表）。
    2. 运行：python scripts/export_boss_cookies.py
    3. 首次运行时 macOS 会弹「钥匙串访问」授权框，点「始终允许」。
    4. 脚本会打印 JSON，并保存到 data/boss_cookies.json（请勿提交）。
"""

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
except ImportError:
    print("缺少 cryptography 依赖，请先运行：pip install cryptography", file=sys.stderr)
    sys.exit(2)

COOKIE_DB = os.path.expanduser(
    "~/Library/Application Support/Google/Chrome/Default/Cookies"
)
OUT_FILE = "data/boss_cookies.json"


def quit_chrome():
    """优雅退出 Chrome，使其把 WAL 日志落盘到 Cookies 数据库。"""
    subprocess.run(["osascript", "-e", 'quit app "Google Chrome"'], check=False)
    time.sleep(3)


def copy_cookie_db() -> str:
    """把 Cookies 及其 WAL 文件复制到临时目录，避免读取时被锁。"""
    tmpdir = tempfile.mkdtemp(prefix="cookies_")
    for suffix in ("", "-wal", "-journal", "-shm"):
        src = COOKIE_DB + suffix
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(tmpdir, "Cookies" + suffix))
    return os.path.join(tmpdir, "Cookies")


def get_safe_storage_key() -> bytes:
    """从 macOS 钥匙串读取 Chrome 的 Cookie 加密密钥。"""
    proc = subprocess.run(
        ["security", "find-generic-password", "-w", "-s", "Chrome Safe Storage"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(
            "无法读取钥匙串密钥。请确认在图形界面的 Mac 上运行，"
            "并在授权弹窗中选择「始终允许」。",
            file=sys.stderr,
        )
        print(proc.stderr, file=sys.stderr)
        sys.exit(1)
    return proc.stdout.strip().encode("utf-8")


def decrypt_v10(safe_key: bytes, encrypted_value: bytes) -> str:
    """解密 Chrome v10 格式的 Cookie。

    实测结构（Chrome 147 / macOS）：
        "v10" + 16 字节(按域名变化的块) + 16 字节随机 IV + AES-128-CBC 密文
    因此需跳过前 32 字节，并用第 16~32 字节作为 IV。
    """
    payload = encrypted_value[3:]  # 去掉 "v10" 前缀
    derived = hashlib.pbkdf2_hmac("sha1", safe_key, b"saltysalt", 1003, 16)
    iv = payload[16:32]
    ciphertext = payload[32:]
    decryptor = Cipher(algorithms.AES(derived), modes.CBC(iv)).decryptor()
    plain = decryptor.update(ciphertext) + decryptor.finalize()
    # 去掉 PKCS#7 填充
    pad_len = plain[-1]
    return plain[:-pad_len].decode("utf-8", errors="replace")


def main():
    print("正在退出 Chrome（保证 Cookie 已落盘）...")
    quit_chrome()

    safe_key = get_safe_storage_key()

    db_copy = copy_cookie_db()
    conn = sqlite3.connect(db_copy)
    rows = conn.execute(
        """
        SELECT host_key, name, path, is_secure, is_httponly, expires_utc, encrypted_value
        FROM cookies
        WHERE host_key LIKE '%zhipin%'
        """
    ).fetchall()
    conn.close()

    if not rows:
        print("❌ 没有找到 zhipin.com 的 Cookie，请先在 Chrome 登录 BOSS 直聘。")
        sys.exit(1)

    cookies = []
    for host_key, name, path, is_secure, is_httponly, expires_utc, enc in rows:
        value = decrypt_v10(safe_key, enc)
        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": host_key,
                "path": path or "/",
                "secure": bool(is_secure),
                "httpOnly": bool(is_httponly),
                # 0 表示会话 Cookie，Playwright 支持负数时间戳表示过期
                "expires": expires_utc / 1000000 - 11644473600 if expires_utc else -1,
            }
        )

    os.makedirs("data", exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)

    print(f"✅ 已导出 {len(cookies)} 条 Cookie 到 {OUT_FILE}\n")
    print("---------- 复制下面内容到 GitHub Secrets: BOSS_COOKIES ----------")
    print(json.dumps(cookies, ensure_ascii=False))
    print("----------------------------------------------------------------")


if __name__ == "__main__":
    main()
