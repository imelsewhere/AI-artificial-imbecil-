from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class KBPaths:
    root: Path
    origins_dir: Path
    cards_dir: Path
    cards_md_dir: Path


@dataclass(frozen=True)
class GigaChatSettings:
    base_url: str
    oauth_url: str
    access_token: str | None
    authorization_key: str | None
    scope: str
    model: str
    verify_ssl_certs: bool
    timeout_s: float
    request_delay_s: float


def load_settings(project_root: Path | None = None) -> tuple[GigaChatSettings, KBPaths]:
    """
    Loads settings from `.env` (if present) and environment variables.
    """
    if project_root is None:
        project_root = Path.cwd()

    # `.env` может отсутствовать — это нормально.
    load_dotenv(project_root / ".env", override=False)

    base_url = os.getenv("GIGACHAT_BASE_URL", "https://gigachat.devices.sberbank.ru/api/v1/")
    oauth_url = os.getenv("GIGACHAT_OAUTH_URL", "https://ngw.devices.sberbank.ru:9443/api/v2/oauth")

    access_token = os.getenv("GIGACHAT_ACCESS_TOKEN") or None
    authorization_key = os.getenv("GIGACHAT_AUTHORIZATION_KEY") or None
    scope = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")

    model = os.getenv("GIGACHAT_MODEL", "GigaChat-2")
    verify_ssl_certs = _env_bool("GIGACHAT_VERIFY_SSL_CERTS", False)
    timeout_s = float(os.getenv("GIGACHAT_TIMEOUT", "60"))
    request_delay_s = float(os.getenv("GIGACHAT_REQUEST_DELAY_S", "0"))

    kb_root = Path(os.getenv("KB_ROOT", "knowledge_base"))
    origins_dir = kb_root / os.getenv("KB_ORIGINS_DIR", "origins")
    cards_dir = kb_root / os.getenv("KB_CARDS_DIR", "cards")
    cards_md_dir = kb_root / os.getenv("KB_CARDS_MD_DIR", "cards_md")

    return (
        GigaChatSettings(
            base_url=base_url,
            oauth_url=oauth_url,
            access_token=access_token,
            authorization_key=authorization_key,
            scope=scope,
            model=model,
            verify_ssl_certs=verify_ssl_certs,
            timeout_s=timeout_s,
            request_delay_s=request_delay_s,
        ),
        KBPaths(root=kb_root, origins_dir=origins_dir, cards_dir=cards_dir, cards_md_dir=cards_md_dir),
    )


