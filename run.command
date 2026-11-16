#!/bin/bash
# macOS：双击即可启动（首次需在「系统设置 → 隐私与安全性」允许）
cd "$(dirname "$0")"
exec python3 app.py
