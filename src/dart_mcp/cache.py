"""디스크 캐시: 공시 원문(rcept_no 단위)과 기업코드 목록.

공시 원문은 불변이므로 만료가 없다. data/<rcept_no>/ 아래에
  <rcept_no>.zip            원본 ZIP
  <원본 파일명>.xml          추출된 XML들
  outline.json              파일별 메타 + 섹션 목차(text 제외)
  sections_<file_id>.json   파일별 섹션 전문(text 포함)
을 둔다.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .document import Section, build_outline, decode_dart_xml, extract_from_zip

if TYPE_CHECKING:
    from .client import DartClient

log = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def default_data_dir() -> Path:
    """DART_DATA_DIR 환경변수 → 없으면 <프로젝트 루트>/data."""
    return Path(os.environ.get("DART_DATA_DIR") or (_PROJECT_ROOT / "data"))


def file_id_of(filename: str, rcept_no: str) -> str:
    """'20250311001085.xml' → 'main', '20250311001085_00760.xml' → '00760'."""
    stem = Path(filename).stem
    if stem == rcept_no:
        return "main"
    m = re.match(re.escape(rcept_no) + r"_(.+)$", stem)
    return m.group(1) if m else stem


@dataclass
class CachedFile:
    file_id: str
    filename: str
    encoding: str
    total_chars: int
    sections: list[Section]

    def outline(self) -> list[dict]:
        return [s.to_outline_dict() for s in self.sections]

    def get_section(self, section_id: str) -> Section | None:
        for s in self.sections:
            if s.id == section_id:
                return s
        return None


@dataclass
class CachedDisclosure:
    rcept_no: str
    files: list[CachedFile] = field(default_factory=list)

    def get_file(self, file_id: str) -> CachedFile | None:
        for f in self.files:
            if f.file_id == file_id:
                return f
        return None


class DisclosureCache:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = Path(data_dir) if data_dir else default_data_dir()
        self._mem: dict[str, CachedDisclosure] = {}

    # ---------------------------------------------------------------- paths
    def _dir(self, rcept_no: str) -> Path:
        return self.data_dir / rcept_no

    def _outline_path(self, rcept_no: str) -> Path:
        return self._dir(rcept_no) / "outline.json"

    def _sections_path(self, rcept_no: str, file_id: str) -> Path:
        return self._dir(rcept_no) / f"sections_{file_id}.json"

    # ---------------------------------------------------------------- public
    def has(self, rcept_no: str) -> bool:
        return rcept_no in self._mem or self._outline_path(rcept_no).exists()

    def get(self, rcept_no: str, client: DartClient | None = None) -> CachedDisclosure:
        """캐시에서 읽고, 없으면 client로 받아 저장한다. client가 None이면 캐시 미스 시 KeyError."""
        if rcept_no in self._mem:
            return self._mem[rcept_no]
        if self._outline_path(rcept_no).exists():
            try:
                disc = self._load(rcept_no)
                self._mem[rcept_no] = disc
                log.info("cache hit (disk): %s", rcept_no)
                return disc
            except (OSError, ValueError, KeyError) as exc:
                log.warning("cache for %s unreadable (%s); re-fetching", rcept_no, exc)
        if client is None:
            raise KeyError(f"{rcept_no} is not cached and no client given")
        log.info("cache miss: fetching %s from DART", rcept_no)
        zip_bytes = client.get_document(rcept_no)
        disc = self.store(rcept_no, zip_bytes)
        return disc

    def store(self, rcept_no: str, zip_bytes: bytes) -> CachedDisclosure:
        """ZIP 바이트를 받아 추출/구조화하고 디스크에 저장한다."""
        d = self._dir(rcept_no)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{rcept_no}.zip").write_bytes(zip_bytes)

        disc = CachedDisclosure(rcept_no)
        for name, data in extract_from_zip(zip_bytes):
            safe_name = Path(name).name
            (d / safe_name).write_bytes(data)
            if not safe_name.lower().endswith((".xml", ".htm", ".html")):
                continue
            _, enc = decode_dart_xml(data)
            sections = build_outline(data)
            total = sum(s.char_count for s in sections)
            disc.files.append(CachedFile(file_id_of(safe_name, rcept_no), safe_name, enc, total, sections))

        # main 먼저, 첨부는 file_id 순
        disc.files.sort(key=lambda f: (f.file_id != "main", f.file_id))
        self._save(disc)
        self._mem[rcept_no] = disc
        return disc

    # ---------------------------------------------------------------- disk I/O
    def _save(self, disc: CachedDisclosure) -> None:
        outline = {
            "rcept_no": disc.rcept_no,
            "files": [
                {
                    "file_id": f.file_id,
                    "filename": f.filename,
                    "encoding": f.encoding,
                    "total_chars": f.total_chars,
                    "sections": f.outline(),
                }
                for f in disc.files
            ],
        }
        self._outline_path(disc.rcept_no).write_text(
            json.dumps(outline, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        for f in disc.files:
            self._sections_path(disc.rcept_no, f.file_id).write_text(
                json.dumps([s.__dict__ for s in f.sections], ensure_ascii=False), encoding="utf-8"
            )

    def _load(self, rcept_no: str) -> CachedDisclosure:
        outline = json.loads(self._outline_path(rcept_no).read_text(encoding="utf-8"))
        disc = CachedDisclosure(rcept_no)
        for f in outline["files"]:
            raw = json.loads(self._sections_path(rcept_no, f["file_id"]).read_text(encoding="utf-8"))
            sections = [Section(**s) for s in raw]
            disc.files.append(CachedFile(f["file_id"], f["filename"], f["encoding"], f["total_chars"], sections))
        return disc
