from __future__ import annotations

import uuid
from dataclasses import dataclass

import requests


@dataclass(frozen=True)
class OAuthToken:
    access_token: str
    expires_at: int | None = None


def fetch_gigachat_access_token(
    *,
    oauth_url: str,
    authorization_key: str,
    scope: str,
    rq_uid: str | None = None,
    timeout_s: float = 30.0,
    verify_ssl: bool = True,
) -> OAuthToken:
    """
    Fetch access_token via OAuth endpoint using Basic Authorization key.
    """
    if not rq_uid:
        rq_uid = str(uuid.uuid4())

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "RqUID": rq_uid,
        "Authorization": f"Basic {authorization_key}",
    }

    resp = requests.post(
        oauth_url,
        headers=headers,
        data={"scope": scope},
        timeout=timeout_s,
        verify=verify_ssl,
    )
    resp.raise_for_status()
    data = resp.json()
    return OAuthToken(
        access_token=data["access_token"],
        expires_at=data.get("expires_at"),
    )


