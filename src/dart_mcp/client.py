"""OpenDART HTTP 클라이언트."""

from __future__ import annotations

import json
import os
import time
import zipfile
import io
from typing import Any

import httpx
from dotenv import load_dotenv
from lxml import etree

BASE_URL = "https://opendart.fss.or.kr/api"
DEFAULT_TIMEOUT = 30.0
MAX_RETRIES = 3


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

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "DartClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
