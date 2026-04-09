"""
Cookie import and storage helpers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List

from src.config import COOKIE_FILENAMES, COOKIE_SERVICE_DOMAINS, COOKIES_DIR


class CookieImportError(Exception):
    """Raised when uploaded cookies cannot be parsed."""


@dataclass(frozen=True)
class CookieImportResult:
    filename: str
    total_lines: int
    service_counts: Dict[str, int]


def _normalize_domain(domain: str) -> str:
    return domain.strip().lower()


def _service_for_domain(domain: str) -> str:
    normalized = _normalize_domain(domain)
    for service, domains in COOKIE_SERVICE_DOMAINS.items():
        for candidate in domains:
            stripped = candidate.lstrip(".")
            if normalized == candidate or normalized == stripped or normalized.endswith(f".{stripped}"):
                return service
    return "global"


def _serialize_entry(parts: List[str]) -> str:
    return "\t".join(parts)


def _cookie_key(parts: List[str]) -> tuple[str, str, str]:
    domain = parts[0].strip().lower() if len(parts) > 0 else ""
    path = parts[2].strip() if len(parts) > 2 else "/"
    name = parts[5].strip() if len(parts) > 5 else ""
    return (domain, path, name)


def _parse_netscape(content: str) -> List[List[str]]:
    entries: List[List[str]] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = raw_line.split("\t")
        if len(parts) < 7:
            continue
        entries.append(parts[:7])
    return entries


def _parse_json(content: str) -> List[List[str]]:
    try:
        cookies = json.loads(content)
    except json.JSONDecodeError as exc:
        raise CookieImportError("Expected Netscape cookies.txt or a JSON cookie array") from exc

    if not isinstance(cookies, list):
        raise CookieImportError("JSON cookies must be an array of objects")

    entries: List[List[str]] = []
    for cookie in cookies:
        if not isinstance(cookie, dict):
            continue
        domain = str(cookie.get("domain", "")).strip()
        name = str(cookie.get("name", "")).strip()
        value = str(cookie.get("value", ""))
        if not domain or not name:
            continue
        path = str(cookie.get("path", "/")) or "/"
        secure = "TRUE" if bool(cookie.get("secure", False)) else "FALSE"
        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        expiry_raw = cookie.get("expirationDate", cookie.get("expires", 0)) or 0
        try:
            expiry = str(int(float(expiry_raw)))
        except (TypeError, ValueError):
            expiry = "0"
        entries.append([domain, include_subdomains, path, secure, expiry, name, value])
    return entries


def _ensure_entries(content: str) -> List[List[str]]:
    entries = _parse_netscape(content)
    if entries:
        return entries
    entries = _parse_json(content)
    if entries:
        return entries
    raise CookieImportError("The file does not contain valid cookies")


def _load_existing_entries(path: Path) -> List[List[str]]:
    if not path.exists():
        return []
    return _parse_netscape(path.read_text(encoding="utf-8", errors="ignore"))


def _merge_entries(existing_entries: List[List[str]], new_entries: List[List[str]]) -> List[str]:
    merged: Dict[tuple[str, str, str], List[str]] = {}
    order: List[tuple[str, str, str]] = []

    for parts in existing_entries:
        key = _cookie_key(parts)
        if not key[2]:
            continue
        if key not in merged:
            order.append(key)
        merged[key] = parts

    for parts in new_entries:
        key = _cookie_key(parts)
        if not key[2]:
            continue
        if key not in merged:
            order.append(key)
        merged[key] = parts

    return [_serialize_entry(merged[key]) for key in order]


def _write_cookie_file(path: Path, entries: Iterable[str]) -> int:
    items = list(entries)
    if not items:
        if path.exists():
            path.unlink()
        return 0

    text = "# Netscape HTTP Cookie File\n\n" + "\n".join(items) + "\n"
    path.write_text(text, encoding="utf-8")
    return len(items)


def import_cookie_file(source_path: Path, original_name: str) -> CookieImportResult:
    content = source_path.read_text(encoding="utf-8", errors="ignore")
    parsed_entries = _ensure_entries(content)

    grouped: Dict[str, List[List[str]]] = {key: [] for key in COOKIE_FILENAMES}
    for parts in parsed_entries:
        service = _service_for_domain(parts[0])
        grouped.setdefault(service, []).append(parts)

    counts: Dict[str, int] = {}
    for service, filename in COOKIE_FILENAMES.items():
        destination = COOKIES_DIR / filename
        existing_entries = _load_existing_entries(destination)
        merged_entries = _merge_entries(existing_entries, grouped.get(service, []))
        count = _write_cookie_file(destination, merged_entries)
        if count:
            counts[service] = count

    return CookieImportResult(
        filename=original_name,
        total_lines=len(parsed_entries),
        service_counts=counts,
    )


def get_cookie_path(service: str) -> str | None:
    service_file = COOKIES_DIR / COOKIE_FILENAMES.get(service, "")
    if service_file.exists():
        return str(service_file)

    fallback = COOKIES_DIR / COOKIE_FILENAMES["global"]
    if fallback.exists():
        return str(fallback)
    return None


def get_cookie_status_lines() -> List[str]:
    details: List[str] = []
    for service, filename in COOKIE_FILENAMES.items():
        path = COOKIES_DIR / filename
        if path.exists():
            count = sum(
                1 for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()
                if line.strip() and not line.startswith("#")
            )
            details.append(f"• {service}: {count} cookies")
        else:
            details.append(f"• {service}: no file")
    return details
