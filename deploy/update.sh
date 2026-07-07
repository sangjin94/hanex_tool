#!/usr/bin/env bash
# 코드 갱신: GitHub 최신 pull 후 nginx 리로드
set -e
DIR="$HOME/hanex_tool"
git -C "$DIR" pull
chmod -R a+rX "$DIR"
# 가온 중계 서버 설정 최신화 + 재시작 (있을 때만)
if [ -f /etc/systemd/system/gaon-proxy.service ]; then
  sudo cp "$DIR/deploy/gaon-proxy.service" /etc/systemd/system/gaon-proxy.service
  sudo systemctl daemon-reload
  sudo systemctl restart gaon-proxy
fi
sudo cp "$DIR/deploy/nginx-hanex.conf" /etc/nginx/sites-available/hanex
sudo nginx -t && sudo systemctl reload nginx
echo "갱신 완료 ($(git -C "$DIR" rev-parse --short HEAD))"
