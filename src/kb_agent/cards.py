from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_sha256(path: Path) -> str:
    h = sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_title(md_text: str, fallback: str) -> str:
    # First H1
    for line in md_text.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


_MD_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
_URL_RE = re.compile(r"https?://[^\s)>\"]+")


def extract_links(md_text: str) -> list[str]:
    links = set()
    for m in _MD_LINK_RE.finditer(md_text):
        links.add(m.group(1).strip())
    for m in _URL_RE.finditer(md_text):
        links.add(m.group(0).strip())
    return sorted(links)


@dataclass
class KnowledgeCard:
    id: str
    title: str
    summary: str
    content_md: str
    card_md_path: str | None
    key_terms: list[str]
    entities: list[str]
    links: list[str]
    created_at: str
    updated_at: str


def card_to_dict(card: KnowledgeCard) -> dict[str, Any]:
    return {
        "id": card.id,
        "title": card.title,
        "summary": card.summary,
        "content_md": card.content_md,
        "card_md_path": card.card_md_path,
        "key_terms": card.key_terms,
        "entities": card.entities,
        "links": card.links,
        "created_at": card.created_at,
        "updated_at": card.updated_at,
    }


def write_card_file(
    *,
    output_path: Path,
    source_rel_path: str,
    source_sha256: str,
    source_modified_at: str | None,
    cards: list[KnowledgeCard],
    quality: dict[str, Any] | None = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 2,
        "source": {
            "path": source_rel_path.replace("\\", "/"),
            "sha256": source_sha256,
            "modified_at": source_modified_at,
        },
        "cards": [card_to_dict(c) for c in cards],
    }
    if quality:
        payload["quality"] = quality
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_card_file_payload(payload: dict[str, Any]) -> tuple[bool, str | None]:
    if not isinstance(payload, dict):
        return False, "payload is not an object"
    if payload.get("schema_version") not in {1, 2}:
        return False, "schema_version must be 1 or 2"
    if "source" not in payload or not isinstance(payload["source"], dict):
        return False, "missing source"
    if "cards" not in payload or not isinstance(payload["cards"], list):
        return False, "missing cards[]"
    if len(payload["cards"]) < 1:
        return False, "cards[] must have at least one element"
    return True, None


