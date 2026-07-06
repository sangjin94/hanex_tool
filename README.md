# HANEX 상품등록 양식 생성기

gaon(hanex.co.kr) WMS 상품등록용 47컬럼 엑셀(.xlsx)을 브라우저에서 생성하는 정적 웹앱입니다.

- 화주사별 프로필(고정값·필수컬럼·메모) 관리
- 엑셀 템플릿 순서 그대로 표(그리드)에 입력/붙여넣기
- 자사상품코드: 접두어(여러 개 가능) + 고객사코드 자동/선택 복사
- gaon 파서 호환을 위해 **공유문자열(sharedStrings)** 구조로 xlsx 생성

## 구성
- `index.html` — 앱 전체 (단일 파일)
- `fflate.js` — xlsx(zip) 생성 라이브러리 (로컬 번들, CDN 불필요)
- `deploy/` — AWS Lightsail(nginx) 배포 스크립트

설정(화주사 프로필)은 브라우저 localStorage에 저장됩니다. 기본 프로필(윌리엄그랜트앤선즈)은 코드에 내장.

## AWS Lightsail 배포 (nginx)

Ubuntu 인스턴스 기준. SSH 접속 후:

```bash
# 1) 최초 1회 설치
curl -fsSL https://raw.githubusercontent.com/sangjin94/hanex_tool/main/deploy/setup-lightsail.sh | bash
```

또는 수동:

```bash
sudo apt update && sudo apt install -y nginx git
git clone https://github.com/sangjin94/hanex_tool.git ~/hanex_tool
sudo cp ~/hanex_tool/deploy/nginx-hanex.conf /etc/nginx/sites-available/hanex
sudo ln -sf /etc/nginx/sites-available/hanex /etc/nginx/sites-enabled/hanex
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx
```

브라우저에서 `http://<인스턴스 퍼블릭 IP>/` 접속.

### 코드 갱신 (git 연동)
로컬에서 수정 → `git push` 후, 서버에서:

```bash
~/hanex_tool/deploy/update.sh
```

## 로컬 개발
정적 파일이라 서버 불필요. `index.html`을 브라우저로 열거나:

```bash
python -m http.server 8899
# http://127.0.0.1:8899/
```
