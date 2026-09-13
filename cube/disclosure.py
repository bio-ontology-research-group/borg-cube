"""Filter secrets and personal records at the laptop's release boundary."""

from __future__ import annotations

import re

SECRET = re.compile(
    r"-----BEGIN .*PRIVATE KEY-----|\b(?:gh[pousr]_[A-Za-z0-9_]{12,}|"
    r"github_pat_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]{16,}|AKIA[A-Z0-9]{16})|"
    r"(?i:password|passwd|api[_ -]?key|access[_ -]?token|client[_ -]?secret)\s*[:=]\s*\S+|"
    r"https?://[^\s/@:]+:[^\s/@]+@|(?i:Bearer)\s+[A-Za-z0-9._~-]+"
)
PERSONAL = re.compile(
    r"\b(?:grades?|gpa|salary|salaries|passport|iqama|disciplinary|"
    r"performance review|medical leave|sick leave|diagnosed with|"
    r"contract (?:renewal|value|expiry)|visa (?:renewal|expiry|application))\b",
    re.I,
)


def release_text(text: str, *, personal_source: bool = False) -> str:
    """Refuse a whole sensitive source; never leak adjacent lines or key fragments."""
    if SECRET.search(text):
        return "[withheld: source contains credentials]"
    if personal_source and PERSONAL.search(text):
        return "[withheld: personal record remains on the laptop]"
    return text
