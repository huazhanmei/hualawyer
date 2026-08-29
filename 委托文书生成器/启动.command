#!/bin/zsh
# 双击本文件即可启动委托文书生成器（仅本机访问）
DIR="$(cd "$(dirname "$0")" && pwd)"
if [ ! -d "$DIR/.venv" ]; then
  echo "首次运行：正在初始化依赖环境……"
  /Users/hua/.workbuddy/binaries/python/versions/3.13.12/bin/python3 -m venv "$DIR/.venv"
  "$DIR/.venv/bin/pip" install -q flask python-docx pillow pyobjc-framework-Vision pyobjc-framework-Quartz
fi
open "http://127.0.0.1:5092"
exec "$DIR/.venv/bin/python" "$DIR/app.py"
