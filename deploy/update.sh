#!/usr/bin/env bash
# 코드 갱신: GitHub 최신 pull 후 nginx 리로드
set -e
DIR="$HOME/hanex_tool"
git -C "$DIR" pull
sudo systemctl reload nginx
echo "갱신 완료 ($(git -C "$DIR" rev-parse --short HEAD))"
