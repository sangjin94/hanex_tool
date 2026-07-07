#!/usr/bin/env bash
# AWS Lightsail(Ubuntu) 최초 설치 스크립트
set -e

REPO="https://github.com/sangjin94/hanex_tool.git"
DIR="$HOME/hanex_tool"

echo "[1/4] 패키지 설치 (nginx, git)"
sudo apt update
sudo apt install -y nginx git

echo "[2/4] 소스 받기"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull
else
  git clone "$REPO" "$DIR"
fi

echo "[3/5] 홈 디렉터리 권한 (nginx 읽기 허용)"
chmod 755 "$HOME"
chmod -R a+rX "$DIR"

echo "[4/5] nginx 설정"
sudo cp "$DIR/deploy/nginx-hanex.conf" /etc/nginx/sites-available/hanex
sudo ln -sf /etc/nginx/sites-available/hanex /etc/nginx/sites-enabled/hanex
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx
sudo systemctl enable nginx

echo "[5/5] 가온 중계 서버(systemd) 설치"
sudo cp "$DIR/deploy/gaon-proxy.service" /etc/systemd/system/gaon-proxy.service
sudo systemctl daemon-reload
sudo systemctl enable gaon-proxy
sudo systemctl restart gaon-proxy

IP=$(curl -s http://checkip.amazonaws.com || echo "<인스턴스 IP>")
echo "완료! 접속: http://$IP/"
