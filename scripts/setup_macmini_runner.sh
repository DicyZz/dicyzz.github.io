#!/bin/bash
# Mac mini 部署 GitHub self-hosted runner（国内家庭 IP，用于抓 BOSS 直聘）
# 用法：在 Mac mini 终端运行  bash scripts/setup_macmini_runner.sh
set -e

REPO_URL="https://github.com/DicyZz/dicyzz.github.io"
RUNNER_DIR="$HOME/actions-runner"

echo "== 1/6 检测架构 =="
ARCH=$(uname -m)
case "$ARCH" in
  arm64) RUNNER_ARCH="arm64" ;;
  x86_64) RUNNER_ARCH="x64" ;;
  *) echo "不支持的架构: $ARCH"; exit 1 ;;
esac
echo "架构: $RUNNER_ARCH"

echo "== 2/6 下载 GitHub runner =="
LATEST=$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest | grep -o '"tag_name": *"[^"]*"' | head -1 | cut -d'"' -f4)
VER="${LATEST#v}"
TARBALL="actions-runner-osx-${RUNNER_ARCH}-${VER}.tar.gz"
URL="https://github.com/actions/runner/releases/download/${LATEST}/${TARBALL}"
mkdir -p "$RUNNER_DIR"
cd "$RUNNER_DIR"
echo "下载 $URL"
curl -fSL -o runner.tar.gz "$URL"
tar xzf runner.tar.gz
rm -f runner.tar.gz

echo "== 3/6 配置 runner =="
echo "请先在浏览器打开仓库：Settings -> Actions -> Runners -> New self-hosted runner"
echo "复制页面生成的 token（第二段，--token 后面的值）"
read -r -p "粘贴 token: " TOKEN
if [ -z "$TOKEN" ]; then echo "token 不能为空"; exit 1; fi
./config.sh --url "$REPO_URL" --token "$TOKEN" --name "macmini" --labels self-hosted --work _work --unattended --replace

echo "== 4/6 安装 Python 依赖与 Chromium =="
if ! command -v python3 >/dev/null; then
  echo "请先安装 Python3（https://www.python.org/downloads/ 或 brew install python）"; exit 1
fi
python3 -m pip install --user --upgrade pip 2>/dev/null || true
python3 -m pip install --user requests markdown premailer openai playwright lxml
python3 -m playwright install chromium

echo "== 5/6 生成开机自启 (LaunchAgent) =="
mkdir -p "$HOME/Library/LaunchAgents"
PLIST="$HOME/Library/LaunchAgents/com.github.actions.runner.plist"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.github.actions.runner</string>
    <key>ProgramArguments</key>
    <array>
        <!-- caffeinate -s：只要有任务在跑就不让机器休眠（服务器场景必需，
             否则 Mac 睡着时收不到 workflow 派发的任务） -->
        <string>/usr/bin/caffeinate</string>
        <string>-s</string>
        <string>/bin/bash</string>
        <string>$RUNNER_DIR/run.sh</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>$RUNNER_DIR</string>
    <key>StandardOutPath</key>
    <string>$RUNNER_DIR/runner.log</string>
    <key>StandardErrPath</key>
    <string>$RUNNER_DIR/runner.log</string>
</dict>
</plist>
EOF
launchctl unload "$PLIST" 2>/dev/null || launchctl bootout "gui/$UID/com.github.actions.runner" 2>/dev/null || true
launchctl load "$PLIST" 2>/dev/null || launchctl bootstrap "gui/$UID" "$PLIST"

echo "== 6/6 登录 BOSS（保存登录态） =="
echo "即将打开浏览器，请用 BOSS App 扫码登录，登录完成后回终端按回车。"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
python3 "$REPO_DIR/scripts/boss_login.py"

echo ""
echo "✅ 全部完成！"
echo "   runner 已开机自启（并用 caffeinate 防止休眠），BOSS 登录态已保存。"
echo "   手机端：GitHub App → Actions → Job Monitor → Run workflow → 直接点 Run。"
echo "   （workflow 默认 runner=self-hosted，就是这台机器）"
echo "   登录态过期时重跑：python3 scripts/boss_login.py"
