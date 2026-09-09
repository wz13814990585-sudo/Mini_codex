"""Conservative secret redaction for persisted observability data."""

import re

_SECRET_KEY = re.compile(
    r"^(?:api[_-]?key|access[_-]?token|auth[_-]?token|refresh[_-]?token|"
    r"secret|password|authorization|cookie)$", re.IGNORECASE,
)
_INLINE = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|authorization)\b\s*[:=]\s*['\"]?([^\s,'\"]+)"
)


def redact(value):
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _SECRET_KEY.search(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _INLINE.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)
    return value
