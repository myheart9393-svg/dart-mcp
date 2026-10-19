"""OpenDART HTTP 클라이언트."""

from __future__ import annotations

import io
import json
import os
import re
import time
import zipfile
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from lxml import etree

BASE_URL = "https://opendart.fss.or.kr/api"
DEFAULT_TIMEOUT = 30.0
MAX_RETRIES = 3
CORP_CODES_MAX_AGE_DAYS = 7


def parse_corp_code_zip(zip_bytes: bytes) -> list[dict]:
    """corpCode.xml ZIP → [{corp_code, corp_name, stock_code, modify_date}, ...]"""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        xml_name = next((n for n in zf.namelist() if n.lower().endswith(".xml")), None)
        if xml_name is None:
            raise DartApiError("???", "corpCode ZIP 안에 XML이 없습니다")
        data = zf.read(xml_name)

    entries: list[dict] = []
    for _event, el in etree.iterparse(io.BytesIO(data), tag="list", recover=True):
        entries.append(
            {
                "corp_code": (el.findtext("corp_code") or "").strip(),
                "corp_name": (el.findtext("corp_name") or "").strip(),
                "stock_code": (el.findtext("stock_code") or "").strip(),
                "modify_date": (el.findtext("modify_date") or "").strip(),
            }
        )
        el.clear()
    return entries


def search_corp_codes(entries: list[dict], name: str, limit: int = 10) -> list[dict]:
    """회사명 부분일치(대소문자·공백 무시). 상장사 우선 → 정확일치 → 이름 길이 순."""
    q = re.sub(r"\s+", "", name).lower()
    if not q:
        return []
    hits = []
    for e in entries:
        n = re.sub(r"\s+", "", e["corp_name"]).lower()
        if q in n:
            hits.append((0 if e["stock_code"] else 1, 0 if n == q else 1, len(n), e))
    hits.sort(key=lambda t: t[:3])
    return [h[3] for h in hits[:limit]]


class DartApiError(Exception):
    """OpenDART가 정상 응답(status 000) 대신 에러를 돌려준 경우."""

    def __init__(self, status: str, message: str):
        self.status = status
        self.message = message
        super().__init__(f"DART API error [status={status}] {message}")


def _parse_error_payload(body: bytes) -> tuple[str, str] | None:
    """JSON 또는 XML 에러 응답에서 (status, message)를 뽑는다. 아니면 None."""
    text = body.lstrip()
    if text.startswith(b"{"):
        try:
            obj = json.loads(text.decode("utf-8", errors="replace"))
        except ValueError:
            return None
        if isinstance(obj, dict) and "status" in obj:
            return str(obj.get("status")), str(obj.get("message", ""))
        return None
    if text.startswith(b"<"):
        try:
            root = etree.fromstring(text, parser=etree.XMLParser(recover=True))
        except etree.XMLSyntaxError:
            return None
        if root is None:
            return None
        status_el = root.find(".//status")
        if status_el is not None:
            msg_el = root.find(".//message")
            return (status_el.text or "").strip(), (msg_el.text or "").strip() if msg_el is not None else ""
    return None


class DartClient:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = MAX_RETRIES,
    ):
        if api_key is None:
            load_dotenv()
            api_key = os.getenv("DART_API_KEY")
        if not api_key:
            raise ValueError("DART_API_KEY가 없습니다. .env 파일 또는 api_key 인자로 전달하세요.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self._http = httpx.Client(timeout=timeout)

    # ---------------------------------------------------------------- internals
    def _get(self, path: str, params: dict[str, Any]) -> httpx.Response:
        """GET 요청. 네트워크 에러에만 지수 백오프 재시도."""
        params = {"crtfc_key": self.api_key, **{k: v for k, v in params.items() if v is not None}}
        url = f"{self.base_url}/{path.lstrip('/')}"
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = self._http.get(url, params=params)
                resp.raise_for_status()
                return resp
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                # 4xx는 재시도해도 의미 없음
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                    raise
                last_exc = exc
                if attempt < self.max_retries - 1:
                    time.sleep(2**attempt)  # 1s, 2s
        assert last_exc is not None
        raise last_exc

    # ---------------------------------------------------------------- public API
    def get_document(self, rcept_no: str) -> bytes:
        """공시 원문 ZIP 바이너리를 반환한다. 에러 응답이면 DartApiError."""
        resp = self._get("document.xml", {"rcept_no": rcept_no})
        body = resp.content
        if body[:2] == b"PK" and zipfile.is_zipfile(io.BytesIO(body)):
            return body
        parsed = _parse_error_payload(body)
        if parsed is not None:
            status, message = parsed
            raise DartApiError(status, message)
        ctype = resp.headers.get("content-type", "")
        raise DartApiError("???", f"ZIP이 아닌 알 수 없는 응답 (content-type={ctype}, {len(body)} bytes)")

    def search_disclosures(
        self,
        corp_code: str | None = None,
        bgn_de: str | None = None,
        end_de: str | None = None,
        pblntf_ty: str | None = None,
        page_no: int = 1,
        page_count: int = 100,
        **extra: Any,
    ) -> dict:
        """공시 목록 조회 (list.json)."""
        resp = self._get(
            "list.json",
            {
                "corp_code": corp_code,
                "bgn_de": bgn_de,
                "end_de": end_de,
                "pblntf_ty": pblntf_ty,
                "page_no": page_no,
                "page_count": page_count,
                **extra,
            },
        )
        data = resp.json()
        if data.get("status") != "000":
            raise DartApiError(str(data.get("status")), str(data.get("message", "")))
        return data

    def get_financial_statements(
        self, corp_code: str, bsns_year: str, reprt_code: str = "11011", fs_div: str = "CFS"
    ) -> dict:
        """단일회사 전체 재무제표 (fnlttSinglAcntAll.json).

        reprt_code: 11011=사업보고서, 11012=반기, 11013=1분기, 11014=3분기. fs_div: CFS=연결, OFS=별도.
        status "013"(조회된 데이터 없음)은 예외 대신 그대로 돌려준다. 그 밖의 비정상 status는 DartApiError.
        """
        resp = self._get(
            "fnlttSinglAcntAll.json",
            {"corp_code": corp_code, "bsns_year": bsns_year, "reprt_code": reprt_code, "fs_div": fs_div},
        )
        data = resp.json()
        status = str(data.get("status"))
        if status not in ("000", "013"):
            raise DartApiError(status, str(data.get("message", "")))
        return data

    # ---------------------------------------------------------------- 기업코드
    def get_corp_codes(
        self,
        cache_path: Path | None = None,
        max_age_days: float = CORP_CODES_MAX_AGE_DAYS,
    ) -> list[dict]:
        """전체 기업코드 목록. data/corp_codes.json 캐시가 max_age_days 이내면 재다운로드하지 않는다.

        각 항목: {"corp_code", "corp_name", "stock_code", "modify_date"}
        """
        if cache_path is None:
            from .cache import default_data_dir

            cache_path = default_data_dir() / "corp_codes.json"

        if cache_path.exists():
            try:
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
                age = time.time() - float(payload.get("fetched_at", 0))
                if age < max_age_days * 86400 and payload.get("list"):
                    return payload["list"]
            except (OSError, ValueError):
                pass

        resp = self._get("corpCode.xml", {})
        body = resp.content
        if body[:2] != b"PK":
            parsed = _parse_error_payload(body)
            if parsed:
                raise DartApiError(*parsed)
            raise DartApiError("???", "corpCode.xml 응답이 ZIP이 아닙니다")

        entries = parse_corp_code_zip(body)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps({"fetched_at": time.time(), "count": len(entries), "list": entries}, ensure_ascii=False),
            encoding="utf-8",
        )
        return entries

    def find_company(self, name: str, limit: int = 10) -> list[dict]:
        """회사명 부분일치 검색. 상장사(stock_code 있음) 우선."""
        return search_corp_codes(self.get_corp_codes(), name, limit)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "DartClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
