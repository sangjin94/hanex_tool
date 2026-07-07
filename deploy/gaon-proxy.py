#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
가온 중계 서버 (hanex_tool 점포등록용)
- 브라우저가 /api/gaon/maxcode 로 {id, pw, ip, marketCode} 를 보내면
  가온에 로그인 → 해당 시장코드의 마지막 STORE_CODE 를 조회해 돌려준다.
- 계정은 서버에 저장하지 않는다. 요청마다 브라우저(localStorage)에서 전달받아 중계만 한다.
- 순수 표준 라이브러리만 사용 (pip 설치 불필요). 127.0.0.1:8080 에서 대기, nginx가 /api/ 로 프록시.
"""
import os
import json
import re
import shutil
import http.cookiejar
import urllib.request
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GAON_HOST = "https://gaon.hanex.co.kr"
LOGIN_URL = GAON_HOST + "/hanex/ex/login.do"
QUERY_URL = GAON_HOST + "/hanex//dynamicService.do"
COMPANY_LOGIN = "100"
COMPANY_QUERY = "001"
LISTEN = ("127.0.0.1", 8080)

# 통합매핑 데이터 저장 위치 (git repo 밖 · 재배포에도 유지)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # hanex_tool
DEFAULT_MAP = os.path.join(BASE_DIR, "data", "mapping.default.json")
DEFAULT_SHIPPERS = os.path.join(BASE_DIR, "data", "shippers.default.json")
DATA_DIR = os.path.join(os.path.expanduser("~"), "hanex_data")
MAP_PATH = os.path.join(DATA_DIR, "mapping.json")
SHIPPERS_PATH = os.path.join(DATA_DIR, "shippers.json")
MAX_UPLOAD = 30 * 1024 * 1024  # 30MB


def read_shippers_bytes():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(SHIPPERS_PATH) and os.path.exists(DEFAULT_SHIPPERS):
        shutil.copyfile(DEFAULT_SHIPPERS, SHIPPERS_PATH)
    if os.path.exists(SHIPPERS_PATH):
        with open(SHIPPERS_PATH, "rb") as f:
            return f.read()
    return b"{}"


def write_shippers_bytes(raw):
    os.makedirs(DATA_DIR, exist_ok=True)
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError("화주사 데이터는 객체여야 합니다")
    tmp = SHIPPERS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, SHIPPERS_PATH)
    return len(obj)


def read_mapping_bytes():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(MAP_PATH) and os.path.exists(DEFAULT_MAP):
        shutil.copyfile(DEFAULT_MAP, MAP_PATH)
    if os.path.exists(MAP_PATH):
        with open(MAP_PATH, "rb") as f:
            return f.read()
    return b'{"v":1,"region":[],"zone":{"liquor":[],"nonfood":[]},"counts":{"region":0,"liquor":0,"nonfood":0}}'


def write_mapping_bytes(raw):
    os.makedirs(DATA_DIR, exist_ok=True)
    obj = json.loads(raw)  # 유효성 검증 (깨진 JSON 저장 방지)
    tmp = MAP_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, MAP_PATH)
    return obj.get("counts", {})


def store_sort_key(code):
    code = "" if code is None else str(code).strip()
    m = re.search(r"(\d+)$", code)
    num = int(m.group(1)) if m else -1
    is_pure_digit = code.isdigit()
    priority = 0 if is_pure_digit else 1
    return (priority, num)


def fetch_max_store_code(user_id, user_pwd, client_ip, market_code):
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    login_payload = f"""<?xml version="1.0" encoding="UTF-8"?>
<Root xmlns="http://www.nexacroplatform.com/platform/dataset">
    <Parameters>
        <Parameter id="sCompanyCd">{COMPANY_LOGIN}</Parameter>
        <Parameter id="sUserId">{user_id}</Parameter>
        <Parameter id="sUserPwd">{user_pwd}</Parameter>
        <Parameter id="sDomain">ko_KR</Parameter>
        <Parameter id="sWebViewType">desktop</Parameter>
        <Parameter id="__tcsFormId">frmLogin</Parameter>
    </Parameters>
</Root>"""
    req = urllib.request.Request(LOGIN_URL, data=login_payload.encode("utf-8"),
                                 headers={"Content-Type": "text/xml"})
    with opener.open(req, timeout=20) as res:
        text = res.read().decode("utf-8", "replace")
    if not re.search(r"ErrorCode=0", text):
        return None, "로그인 실패 (아이디/비밀번호 확인)"

    query_payload = f"""<?xml version="1.0" encoding="UTF-8"?>
<Root xmlns="http://www.nexacroplatform.com/platform/dataset">
    <Parameters>
        <Parameter id="sCompanyCode">{COMPANY_QUERY}</Parameter>
        <Parameter id="sMarketCode">{market_code}</Parameter>
        <Parameter id="sStoreCode"></Parameter>
        <Parameter id="sOtherStoreCode"></Parameter>
        <Parameter id="sIdentiNo"></Parameter>
        <Parameter id="sFlag">0</Parameter>
        <Parameter id="sUserId">%</Parameter>
        <Parameter id="commonVar1">{client_ip}</Parameter>
    </Parameters>
    <Dataset id="dsService">
        <ColumnInfo>
            <Column id="name" type="string" size="256"/>
            <Column id="inMapping" type="string" size="256"/>
            <Column id="inputDataset" type="string" size="256"/>
            <Column id="outMapping" type="string" size="256"/>
            <Column id="strParam" type="string" size="256"/>
            <Column id="useRowType" type="string" size="256"/>
            <Column id="condition" type="string" size="256"/>
        </ColumnInfo>
        <Rows>
            <Row>
                <Col id="name">Mdm.Wms.P000000394_marketStore_S</Col>
                <Col id="inMapping">gdsComIn=gdsComIn</Col>
                <Col id="inputDataset">gdsComIn=gdsComIn</Col>
                <Col id="outMapping">dsMarketStoreList=Dataset0</Col>
                <Col id="strParam">sCompanyCode="{COMPANY_QUERY}" sMarketCode="{market_code}" sStoreCode="" sOtherStoreCode="" sIdentiNo="" sFlag="0" sUserId="%""</Col>
                <Col id="useRowType">rowType</Col>
            </Row>
        </Rows>
    </Dataset>
    <Dataset id="dsServiceOption">
        <ColumnInfo><Column id="mybatisExecutorType" type="string" size="256"/></ColumnInfo>
        <Rows><Row><Col id="mybatisExecutorType">simple</Col></Row></Rows>
    </Dataset>
    <Dataset id="gdsComIn">
        <ColumnInfo>
            <Column id="userId" type="string" size="255"/>
            <Column id="clientIP" type="string" size="255"/>
        </ColumnInfo>
        <Rows>
            <Row>
                <Col id="userId">{user_id}</Col>
                <Col id="clientIP">{client_ip}</Col>
            </Row>
        </Rows>
    </Dataset>
</Root>"""
    req2 = urllib.request.Request(QUERY_URL, data=query_payload.encode("utf-8"),
                                  headers={"Content-Type": "text/xml"})
    with opener.open(req2, timeout=30) as res2:
        content = res2.read()

    ns = {"ns": "http://www.nexacroplatform.com/platform/dataset"}
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return None, "응답 파싱 실패"

    codes = []
    for ds in root.findall(".//ns:Dataset", ns):
        rows = ds.find("ns:Rows", ns)
        if rows is None:
            continue
        for row in rows.findall("ns:Row", ns):
            cols = {col.attrib.get("id"): (col.text or "") for col in row.findall("ns:Col", ns)}
            sc = cols.get("STORE_CODE") or cols.get("StoreCode") or cols.get("store_code") or ""
            sc = (sc or "").strip()
            if sc:
                codes.append(sc)

    if not codes:
        return "", None  # 조회는 됐으나 점포 없음
    return max(codes, key=store_sort_key), None


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_raw(self, code, body, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        path = self.path.rstrip("/")
        if path == "/api/mapping":
            try:
                n = int(self.headers.get("Content-Length", 0))
                if n <= 0 or n > MAX_UPLOAD:
                    self._send(400, {"ok": False, "error": "크기 오류"})
                    return
                raw = self.rfile.read(n)
                counts = write_mapping_bytes(raw)
                self._send(200, {"ok": True, "counts": counts})
            except Exception as e:
                self._send(200, {"ok": False, "error": "저장 실패: " + str(e)})
            return
        if path == "/api/shippers":
            try:
                n = int(self.headers.get("Content-Length", 0))
                if n <= 0 or n > MAX_UPLOAD:
                    self._send(400, {"ok": False, "error": "크기 오류"})
                    return
                cnt = write_shippers_bytes(self.rfile.read(n))
                self._send(200, {"ok": True, "count": cnt})
            except Exception as e:
                self._send(200, {"ok": False, "error": "저장 실패: " + str(e)})
            return
        if path != "/api/gaon/maxcode":
            self._send(404, {"ok": False, "error": "not found"})
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            self._send(400, {"ok": False, "error": "bad json"})
            return
        uid = str(data.get("id", "")).strip()
        pw = str(data.get("pw", "")).strip()
        ip = str(data.get("ip", "")).strip()
        mk = str(data.get("marketCode", "")).strip()
        if not (uid and pw and mk):
            self._send(400, {"ok": False, "error": "id/pw/marketCode 필수"})
            return
        try:
            code, err = fetch_max_store_code(uid, pw, ip, mk)
            if err:
                self._send(200, {"ok": False, "error": err})
            else:
                self._send(200, {"ok": True, "maxCode": code})
        except Exception as e:
            self._send(200, {"ok": False, "error": str(e)})

    def do_GET(self):
        path = self.path.rstrip("/")
        if path == "/api/health":
            self._send(200, {"ok": True})
        elif path == "/api/mapping":
            try:
                self._send_raw(200, read_mapping_bytes())
            except Exception as e:
                self._send(200, {"ok": False, "error": str(e)})
        elif path == "/api/shippers":
            try:
                self._send_raw(200, read_shippers_bytes())
            except Exception as e:
                self._send(200, {"ok": False, "error": str(e)})
        else:
            self._send(404, {"ok": False, "error": "not found"})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    srv = ThreadingHTTPServer(LISTEN, Handler)
    print(f"gaon-proxy listening on {LISTEN[0]}:{LISTEN[1]}")
    srv.serve_forever()
