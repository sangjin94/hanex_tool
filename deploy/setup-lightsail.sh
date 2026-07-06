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

echo "[3/4] nginx 설정"
sudo cp "$DIR/deploy/nginx-hanex.conf" /etc/nginx/sites-available/hanex
sudo ln -sf /etc/nginx/sites-available/hanex /etc/nginx/sites-enabled/hanex
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t

echo "[4/4] nginx 재시작"
sudo systemctl restart nginx
sudo systemctl enable nginx

IP=$(curl -s http://checkip.amazonaws.com || echo "<인스턴스 IP>")
echo "완료! 접속: http://$IP/"
