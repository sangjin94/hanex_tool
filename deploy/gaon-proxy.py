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
import socket
import base64
import datetime
import uuid
from xml.sax.saxutils import escape as xml_esc
import http.cookiejar
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GAON_HOST = os.environ.get("GAON_HOST", "https://gaon.hanex.co.kr")
LOGIN_URL = GAON_HOST + "/hanex/ex/login.do"
QUERY_URL = GAON_HOST + "/hanex//dynamicService.do"
ADDR_URL = GAON_HOST + "/hanex/wms/addrPostSet.do"
ITEM_UPLOAD_URL = GAON_HOST + "/hanex/wms/ifItemUpload.do"
NS = {"ns": "http://www.nexacroplatform.com/platform/dataset"}
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


def gaon_login(user_id, user_pwd):
    """가온 로그인. 성공 시 (세션 쿠키가 담긴 opener, None), 실패 시 (None, 오류메시지)"""
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    login_payload = f"""<?xml version="1.0" encoding="UTF-8"?>
<Root xmlns="http://www.nexacroplatform.com/platform/dataset">
    <Parameters>
        <Parameter id="sCompanyCd">{COMPANY_LOGIN}</Parameter>
        <Parameter id="sUserId">{xml_esc(user_id)}</Parameter>
        <Parameter id="sUserPwd">{xml_esc(user_pwd)}</Parameter>
        <Parameter id="sDomain">ko_KR</Parameter>
        <Parameter id="sWebViewType">desktop</Parameter>
        <Parameter id="__tcsFormId">frmLogin</Parameter>
    </Parameters>
</Root>"""
    req = urllib.request.Request(LOGIN_URL, data=login_payload.encode("utf-8"),
                                 headers={"Content-Type": "text/xml"})
    with opener.open(req, timeout=30) as res:
        text = res.read().decode("utf-8", "replace")
    if not re.search(r"ErrorCode=0", text):
        return None, "로그인 실패 (아이디/비밀번호 확인)"
    return opener, None


def fetch_market_stores(opener, user_id, client_ip, market_code):
    """시장코드의 전체 점포 조회. (점포행 목록, 오류메시지)"""
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
    # 큰 화주(예: 스타로지스)는 점포 전체 목록을 받아오느라 응답이 느리다.
    # 30초로는 경계선에서 간헐적으로 시간초과가 나므로 넉넉히 주고, 한 번 재시도한다.
    req2 = urllib.request.Request(QUERY_URL, data=query_payload.encode("utf-8"),
                                  headers={"Content-Type": "text/xml"})
    content = None
    last_err = None
    for attempt in range(2):
        try:
            with opener.open(req2, timeout=150) as res2:
                content = res2.read()
            break
        except (TimeoutError, socket.timeout, urllib.error.URLError) as e:
            last_err = e
    if content is None:
        return None, "점포 조회 시간초과 (화주 점포 수가 많습니다): " + str(last_err)

    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return None, "응답 파싱 실패"

    codes = []
    for ds in root.findall(".//ns:Dataset", NS):
        rows = ds.find("ns:Rows", NS)
        if rows is None:
            continue
        for row in rows.findall("ns:Row", NS):
            cols = {col.attrib.get("id"): (col.text or "") for col in row.findall("ns:Col", NS)}
            sc = cols.get("STORE_CODE") or cols.get("StoreCode") or cols.get("store_code") or ""
            sc = (sc or "").strip()
            if sc:
                codes.append(sc)
    return codes, None


def fetch_max_store_code(user_id, user_pwd, client_ip, market_code):
    opener, err = gaon_login(user_id, user_pwd)
    if err:
        return None, err
    codes, err = fetch_market_stores(opener, user_id, client_ip, market_code)
    if err:
        return None, err
    if not codes:
        return "", None  # 조회는 됐으나 점포 없음
    return max(codes, key=store_sort_key), None


# ===================== 가온 화면 호출 공통 =====================
SERVICE_COLUMNS = "".join(f'<Column id="{c}" type="string" size="256"/>' for c in
                          ("name", "inMapping", "inputDataset", "outMapping", "strParam", "useRowType", "condition"))
LOG_COLUMNS = "".join(f'<Column id="{c}" type="string" size="256"/>' for c in
                      ("company_cd", "system_div", "user_id", "user_nm", "log_type", "prog_id", "ip_addr",
                       "remark", "session_dt")) + '<Column id="DataSetRowType" type="int" size="4"/>'


def parse_gaon_response(content):
    """(ErrorCode, ErrorMsg, {데이터셋ID: [행]})"""
    root = ET.fromstring(content)
    params = {p.attrib.get("id"): (p.text or "") for p in root.findall(".//ns:Parameter", NS)}
    sets = {}
    for ds in root.findall("ns:Dataset", NS):
        rows = ds.find("ns:Rows", NS)
        sets[ds.attrib.get("id")] = [] if rows is None else [
            {col.attrib.get("id"): (col.text or "") for col in row.findall("ns:Col", NS)}
            for row in rows.findall("ns:Row", NS)]
    return params.get("ErrorCode", ""), params.get("ErrorMsg", ""), sets


def post_gaon(opener, url, body, content_type="text/xml", timeout=150):
    # 쓰기 요청도 지나가므로 재시도하지 않는다 (중복 등록 방지)
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": content_type, "X-Requested-With": "XMLHttpRequest", "Referer": GAON_HOST + "/"})
    with opener.open(req, timeout=timeout) as res:
        return res.read()


def dynamic_service_xml(services, user_id, client_ip, prog_id, remark, extra_datasets):
    """dynamicService.do 요청. 가온 화면이 남기는 이력(Sys.Log.logInsert)을 동일하게 남기고, 이 도구 경유임을 표시한다.
    services: (서비스명, 입력매핑, 입력데이터셋, 출력매핑)"""
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    log = {"company_cd": COMPANY_LOGIN, "system_div": "desktop", "user_id": user_id, "user_nm": user_id,
           "log_type": "SEARCH", "prog_id": prog_id, "ip_addr": client_ip, "remark": ("[hanex_tool] " + remark)[:900],
           "session_dt": now.strftime("%Y-%m-%d %H:%M"), "DataSetRowType": "1"}
    log_row = "".join(f'<Col id="{k}">{xml_esc(v)}</Col>' for k, v in log.items() if v)
    rows = [("Sys.Log.logInsert", "dsHistoryLog=dsHistoryLog gdsComIn=gdsComIn",
             "dsHistoryLog=dsHistoryLog:U gdsComIn=gdsComIn", "")] + services
    svc_rows = "".join(
        f'<Row><Col id="name">{n}</Col><Col id="inMapping">{im}</Col><Col id="inputDataset">{ids}</Col>'
        + (f'<Col id="outMapping">{om}</Col>' if om else "") + '<Col id="useRowType">rowType</Col></Row>'
        for n, im, ids, om in rows)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Root xmlns="http://www.nexacroplatform.com/platform/dataset">
<Parameters><Parameter id="commonVar1">#{{clientIP}}</Parameter></Parameters>
<Dataset id="dsService"><ColumnInfo>{SERVICE_COLUMNS}</ColumnInfo><Rows>{svc_rows}</Rows></Dataset>
<Dataset id="dsServiceOption"><ColumnInfo><Column id="mybatisExecutorType" type="string" size="256"/></ColumnInfo><Rows><Row><Col id="mybatisExecutorType">simple</Col></Row></Rows></Dataset>
<Dataset id="dsHistoryLog"><ColumnInfo>{LOG_COLUMNS}</ColumnInfo><Rows><Row type="insert">{log_row}</Row></Rows></Dataset>
<Dataset id="gdsComIn"><ColumnInfo><Column id="userId" type="string" size="255"/><Column id="clientIP" type="string" size="255"/></ColumnInfo><Rows><Row><Col id="userId">#{{userId}}</Col><Col id="clientIP">#{{clientIP}}</Col></Row></Rows></Dataset>
{extra_datasets}
</Root>""".encode("utf-8")


# ===================== 점포 직접 등록 (P000000253 화면 재현) =====================
# (컬럼ID, 타입, 크기) — 가온 화면의 dsList/dsStores 와 같은 순서
STORE_COLUMNS = [
    ("OTHER_COMPANY_STORE_CODE", "string", 100), ("STORE_CODE", "string", 10), ("STORE_NAME", "string", 50),
    ("INPUT_ZIPNO", "string", 7), ("INPUT_ADDR", "string", 150), ("ADDRPART1", "string", 100), ("ZIPNO", "string", 7),
    ("TELEPHONE_NO", "string", 40), ("FAX_NO", "string", 15), ("HP_NO", "string", 15),
    ("IDENTIFICATION_NO", "string", 15), ("MANAGER_NAME", "string", 30),
    ("BUSINESS_CONDITIONS", "string", 50), ("BUSINESS_ITEM", "string", 50),
    ("OTHER_COMPANY_SELLER_CODE", "string", 10), ("OTHER_COMPANY_SELLER_NAME", "string", 30),
    ("OTHER_COMPANY_SELLER_HP", "string", 25), ("OTHER_COMPANY_SELLER_EMAIL", "string", 32),
    ("MARKET_CODE", "string", 5), ("BUSINESS_FLAG", "string", 3), ("AREA_CODE", "string", 2),
    ("STORE_USER", "string", 30), ("REQ_TIME", "string", 6), ("SECRETE_MANAGEMENT_FLAG", "string", 1),
    ("DELIVERY_STORE_TYPE", "string", 5), ("TOTAL_STORE_CODE", "string", 10), ("TURN_NUMBER", "string", 2),
    ("WAREHOUSE_CODE", "string", 10), ("DELIVERY_REGION_CODE", "string", 5),
    ("COORD_X", "bigdecimal", 32), ("COORD_Y", "bigdecimal", 32), ("CHK", "string", 1),
    ("CURRROW", "bigdecimal", 39), ("DUTYFREE", "string", 1), ("OLD_OTHER_STORE_CODE", "string", 100),
]
STORE_COLUMN_IDS = {c[0] for c in STORE_COLUMNS}
MAX_STORE_ROWS = 5000
REGIST_SVC = "Mdm.Wms.P000000253_storeRegist_I"


def store_dataset_xml(ds_id, rows, row_type=None):
    info = "".join(f'<Column id="{c}" type="{t}" size="{n}"/>' for c, t, n in STORE_COLUMNS)
    attr = f' type="{row_type}"' if row_type else ""
    body = []
    for r in rows:
        cols = "".join(f'<Col id="{c}">{xml_esc(str(r[c]))}</Col>' for c, _, _ in STORE_COLUMNS
                       if str(r.get(c, "") or "").strip())
        body.append(f"<Row{attr}>{cols}</Row>")
    return f'<Dataset id="{ds_id}"><ColumnInfo>{info}</ColumnInfo><Rows>{"".join(body)}</Rows></Dataset>'


def clean_store_rows(rows):
    """브라우저가 보낸 행에서 정의된 컬럼만 남긴다. CHK/CURRROW 는 화면과 동일하게 채운다."""
    out = []
    for i, r in enumerate(rows):
        row = {k: str(v).strip() for k, v in r.items() if k in STORE_COLUMN_IDS and v not in (None, "")}
        row["CHK"] = "1"
        row["CURRROW"] = str(i)
        out.append(row)
    return out


def refine_store_addresses(opener, rows):
    """가온 주소정제. 입력주소 → ADDRPART1/ZIPNO/좌표가 채워진 행 목록"""
    payload = ('<?xml version="1.0" encoding="UTF-8"?>'
               '<Root xmlns="http://www.nexacroplatform.com/platform/dataset">'
               '<Parameters><Parameter id="__tcsFormId">P000000253</Parameter></Parameters>'
               + store_dataset_xml("dsList", rows) + "</Root>")
    code, msg, sets = parse_gaon_response(post_gaon(opener, ADDR_URL, payload.encode("utf-8")))
    if code != "0":
        raise RuntimeError("주소정제 실패: " + (msg or code))
    return sets.get("dsList", [])


def prepare_stores(user_id, user_pwd, client_ip, market_code, rows):
    """등록 전 점검: 기존 점포코드 중복 확인 + 주소정제. 점포 데이터는 쓰지 않는다."""
    opener, err = gaon_login(user_id, user_pwd)
    if err:
        return {"ok": False, "error": err}
    codes, err = fetch_market_stores(opener, user_id, client_ip, market_code)
    if err:
        return {"ok": False, "error": err}
    exist = set(codes)
    refined = {r.get("CURRROW"): r for r in refine_store_addresses(opener, rows)}
    result = []
    for r in rows:
        row = refined.get(r["CURRROW"]) or r
        if r.get("STORE_CODE") in exist:
            status, note = "dup", "이미 가온에 있는 점포코드"
        elif not (row.get("ADDRPART1") or "").strip() or not (row.get("ZIPNO") or "").strip():
            status, note = "addr", "주소 정제 실패 (주소 확인 필요)"
        else:
            status, note = "ok", ""
        result.append({"row": row, "status": status, "note": note})
    return {"ok": True, "rows": result}


def register_stores(user_id, user_pwd, client_ip, rows):
    """점포 등록 저장 (P000000253_storeRegist_I). 가온 운영 데이터에 실제로 들어간다."""
    opener, err = gaon_login(user_id, user_pwd)
    if err:
        return {"ok": False, "error": err}
    codes = ",".join(r.get("STORE_CODE", "") for r in rows)
    payload = dynamic_service_xml(
        [(REGIST_SVC, "dsInputData=dsStores gdsComIn=gdsComIn", "dsInputData=dsStores:U gdsComIn=gdsComIn", "")],
        user_id, client_ip, "P000000253", f"[SVC] {REGIST_SVC} :: {len(rows)}건 :: STORE_CODE={codes}",
        store_dataset_xml("dsStores", rows, "insert"))
    code, msg, sets = parse_gaon_response(post_gaon(opener, QUERY_URL, payload, timeout=180))
    if code != "0":
        return {"ok": False, "error": msg or ("ErrorCode " + code)}
    done = [r for r in sets.get("RESULT_P000000253_storeRegist_I", []) if int(r.get("ROWINDEX") or -1) >= 0]
    return {"ok": True, "inserted": len(done), "requested": len(rows)}


def verify_stores(user_id, user_pwd, client_ip, market_code, codes):
    """등록 후 확인: 요청한 점포코드가 가온 점포목록에 실제로 있는지"""
    opener, err = gaon_login(user_id, user_pwd)
    if err:
        return {"ok": False, "error": err}
    found, err = fetch_market_stores(opener, user_id, client_ip, market_code)
    if err:
        return {"ok": False, "error": err}
    exist = set(found)
    return {"ok": True, "found": [c for c in codes if c in exist], "missing": [c for c in codes if c not in exist]}


# ===================== 상품 인터페이스 업로드 (P000000386 화면 재현) =====================
ITEM_SEARCH_SVC = "Mdm.Wms.P000000386_upItemNew_S"


def search_item_interface(opener, user_id, client_ip, market_code):
    """인터페이스 상품 목록 조회 (업로드 후 화면에 뜨는 목록)"""
    search = ('<Dataset id="dsSearch"><ColumnInfo>'
              + "".join(f'<Column id="{c}" type="string" size="256"/>' for c in
                        ("WMS_COMPANY_CD", "SEARCH_MARKET", "SEARCH_SUPPLIER_ITEM_CODE"))
              + f'</ColumnInfo><Rows><Row><Col id="WMS_COMPANY_CD">{COMPANY_QUERY}</Col>'
              + f'<Col id="SEARCH_MARKET">{xml_esc(market_code)}</Col></Row></Rows></Dataset>')
    payload = dynamic_service_xml(
        [(ITEM_SEARCH_SVC, "dsSearch=dsSearch gdsComIn=gdsComIn", "dsSearch=dsSearch gdsComIn=gdsComIn", "dsMain=dsMain")],
        user_id, client_ip, "P000000386", f"[SVC] {ITEM_SEARCH_SVC} :: SEARCH_MARKET={market_code}", search)
    code, msg, sets = parse_gaon_response(post_gaon(opener, QUERY_URL, payload))
    if code != "0":
        raise RuntimeError("상품 목록 조회 실패: " + (msg or code))
    return [{"code": r.get("SUPPLIER_ITEM_CODE", ""), "ownCode": r.get("ITEM_CODE", ""), "name": r.get("ITEM_NAME", ""),
             "addDate": r.get("ADDDATE", "")} for r in sets.get("dsMain", [])]


def item_interface_list(user_id, user_pwd, client_ip, market_code):
    opener, err = gaon_login(user_id, user_pwd)
    if err:
        return {"ok": False, "error": err}
    return {"ok": True, "rows": search_item_interface(opener, user_id, client_ip, market_code)}


def upload_item_file(user_id, user_pwd, client_ip, market_code, file_name, data):
    """상품 엑셀 업로드 (화면의 엑셀 업로드 버튼과 동일) 후 목록을 다시 조회해 돌려준다."""
    if data[:2] != b"PK":
        return {"ok": False, "error": "xlsx 파일이 아닙니다"}
    opener, err = gaon_login(user_id, user_pwd)
    if err:
        return {"ok": False, "error": err}
    boundary = "----hanexTool" + uuid.uuid4().hex
    safe_name = re.sub(r'["\r\n]', "", file_name) or "upload.xlsx"
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="upfile0"; filename="{safe_name}"\r\n'
            "Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n"
            ).encode("utf-8") + data + f"\r\n--{boundary}--\r\n".encode("utf-8")
    code, msg, _ = parse_gaon_response(post_gaon(
        opener, ITEM_UPLOAD_URL, body, content_type="multipart/form-data; boundary=" + boundary, timeout=180))
    if code != "0":
        return {"ok": False, "error": msg or ("ErrorCode " + code)}
    try:
        return {"ok": True, "rows": search_item_interface(opener, user_id, client_ip, market_code)}
    except Exception as e:
        return {"ok": True, "rows": None, "warning": str(e)}


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
        if path.startswith("/api/gaon/store/") or path.startswith("/api/gaon/item/"):
            self._handle_register(path)
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

    def _handle_register(self, path):
        try:
            n = int(self.headers.get("Content-Length", 0))
            if n <= 0 or n > MAX_UPLOAD:
                self._send(400, {"ok": False, "error": "크기 오류"})
                return
            data = json.loads(self.rfile.read(n))
        except Exception:
            self._send(400, {"ok": False, "error": "bad json"})
            return
        uid = str(data.get("id", "")).strip()
        pw = str(data.get("pw", "")).strip()
        ip = str(data.get("ip", "")).strip()
        mk = str(data.get("marketCode", "")).strip()
        if not (uid and pw):
            self._send(400, {"ok": False, "error": "id/pw 필수"})
            return
        try:
            if path == "/api/gaon/item/list":
                self._send(200, item_interface_list(uid, pw, ip, mk))
            elif path == "/api/gaon/item/upload":
                file_data = base64.b64decode(str(data.get("fileBase64", "")))
                self._send(200, upload_item_file(uid, pw, ip, mk, str(data.get("fileName", "")), file_data))
            elif path == "/api/gaon/store/verify":
                self._send(200, verify_stores(uid, pw, ip, mk, [str(c) for c in data.get("codes", [])]))
            elif path in ("/api/gaon/store/prepare", "/api/gaon/store/register"):
                rows = clean_store_rows(data.get("rows") or [])
                if not rows or len(rows) > MAX_STORE_ROWS:
                    self._send(400, {"ok": False, "error": f"행 수 오류 (1~{MAX_STORE_ROWS}건)"})
                elif path.endswith("/prepare"):
                    self._send(200, prepare_stores(uid, pw, ip, mk, rows))
                else:
                    self._send(200, register_stores(uid, pw, ip, rows))
            else:
                self._send(404, {"ok": False, "error": "not found"})
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
