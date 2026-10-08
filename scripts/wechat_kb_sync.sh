#!/bin/bash
# 公众号知识库：一次抓取 → 分类 → 去重合并 → 导出。
#
# 依赖：
#   1. wewe-rss 已在 Mac mini 上跑起来（Docker，默认 127.0.0.1:4000）
#   2. 可选 DEEPSEEK_API_KEY（用于自动打标签/摘要/主题合并）
#
# 用法：
#   bash scripts/wechat_kb_sync.sh
#
# 环境变量（写进 ~/.config/briefing-secrets.env 或本文件）：
#   WEWE_RSS_BASE=http://127.0.0.1:4000
#   DEEPSEEK_API_KEY=sk-...
#   DEEPSEEK_MODEL=deepseek-chat

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SECRETS_FILE="${BRIEFINGS_SECRETS:-$HOME/.config/briefing-secrets.env}"
PYTHON="${BRIEFINGS_PYTHON:-/opt/homebrew/bin/python3}"
LOG_DIR="${BRIEFINGS_LOG_DIR:-$HOME/Library/Logs/briefings}"

mkdir -p "${LOG_DIR}"
exec >>"${LOG_DIR}/wechat-kb-$(date +%Y-%m-%d).log" 2>&1

# 密钥可选加载（没有 DEEPSEEK 也能跑，只是不 AI 分类）
if [ -f "${SECRETS_FILE}" ]; then
  set -a
  # shellcheck disable=SC1090
  . "${SECRETS_FILE}"
  set +a
fi

if [ ! -x "${PYTHON}" ]; then
  PYTHON="$(command -v python3 || true)"
fi
if [ -z "${PYTHON}" ]; then
  echo "❌ 找不到 python3"
  exit 1
fi

cd "${REPO_DIR}" || { echo "❌ 仓库目录不存在：${REPO_DIR}"; exit 1; }

echo "===== $(date '+%F %T') 开始同步公众号知识库 ====="
"${PYTHON}" scripts/wechat_kb.py full
code=$?
echo "===== 结束 exit=${code} $(date '+%F %T') ====="
exit "${code}"
