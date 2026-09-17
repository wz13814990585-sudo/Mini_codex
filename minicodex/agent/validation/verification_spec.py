"""Typed, tool-independent descriptions of what a validation check proves."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class FileVerificationSpec:
    path: str
    exists: bool = True
    contains: str = ""


@dataclass(frozen=True)
class TestVerificationSpec:
    source_path: str = ""
    test_target: str = ""


@dataclass(frozen=True)
class CommandVerificationSpec:
    command: str


@dataclass(frozen=True)
class HttpVerificationSpec:
    method: str
    path: str
    expected_status: int
    expected_text: str = ""
    json_body: dict | None = None


@dataclass(frozen=True)
class BrowserVerificationSpec:
    path: str
    selector: str = ""
    action: str = ""
    value: str = ""
    expected_text: str = ""


@dataclass(frozen=True)
class SemanticVerificationSpec:
    path: str
    claim: str


VerificationSpec = (FileVerificationSpec | TestVerificationSpec | CommandVerificationSpec |
                    HttpVerificationSpec | BrowserVerificationSpec | SemanticVerificationSpec)


def derive_http_spec(observable: str) -> HttpVerificationSpec | None:
    """Bounded extraction of the small HTTP contract language we support."""
    match = re.search(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/[^\s,→]+).*?\b(\d{3})\b", observable, re.I)
    if not match:
        return None
    method, path, status = match.groups()
    return HttpVerificationSpec(method.upper(), path.rstrip(".,;") or "/", int(status))
