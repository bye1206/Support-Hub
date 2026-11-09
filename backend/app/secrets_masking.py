"""Secret masking for logs (AGENTS.md §6: never log tokens/passwords/secrets).

Pattern-based masking is applied to every log message before serialization.
It is a defense-in-depth measure; code must still avoid putting secrets into
log messages in the first place.
"""

import re

_SECRET_PATTERNS = [
    # Authorization: Bearer <token> / Authorization: Basic ...
    re.compile(r"(?i)(authorization\s*:\s*(?:bearer|basic)\s+)\S+"),
    # password=... / token: ... / MINIO_SECRET_KEY: ... / access_key=... etc.
    # Any prefix ending in a keyword (e.g. "MINIO_SECRET_KEY") also matches.
    # Over-masking in logs is acceptable; missing a secret is not.
    re.compile(r"(?i)([\w-]*(?:password|passwd|secret|token|key)\s*[=:]\s*)\S+"),
]


def mask_secrets(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(r"\1***", text)
    return text
