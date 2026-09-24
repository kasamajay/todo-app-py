"""Encoding helpers that reproduce Go's encoding/json output byte-for-byte
where the frontend or the on-disk data files depend on it.

- time.Time marshals as RFC3339Nano: fractional seconds with trailing zeros
  trimmed (no fraction at all when zero), "Z" for UTC, "+hh:mm" otherwise.
  The zero time is "0001-01-01T00:00:00Z" and is always emitted (encoding/json's
  omitempty never applies to structs).
- []byte marshals as standard base64 (with padding); a nil slice is null.
"""

import base64
import re
from datetime import datetime, timedelta, timezone

ZERO_TIME = datetime(1, 1, 1, tzinfo=timezone.utc)

_RFC3339_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})$"
)


def now() -> datetime:
    return datetime.now(timezone.utc)


def is_zero(t: datetime) -> bool:
    return t == ZERO_TIME


def format_time(t: datetime) -> str:
    """Format like Go's time.Time.MarshalJSON (RFC3339Nano)."""
    base = t.strftime("%Y-%m-%dT%H:%M:%S")
    if t.year < 1000:
        # strftime doesn't zero-pad years below 1000 on every platform.
        base = f"{t.year:04d}" + base[base.index("-"):]
    if t.microsecond:
        base += "." + f"{t.microsecond:06d}".rstrip("0")
    offset = t.utcoffset()
    if offset is None or offset == timedelta(0):
        return base + "Z"
    total = int(offset.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    return f"{base}{sign}{total // 3600:02d}:{(total % 3600) // 60:02d}"


def parse_time(raw: str) -> datetime:
    """Parse an RFC3339 timestamp the way Go's time.Parse(time.RFC3339, ...)
    does, including Go's 9-digit fractional seconds (truncated to the
    microsecond precision Python supports). Raises ValueError if invalid."""
    if not isinstance(raw, str):
        raise ValueError("timestamp must be a string")
    m = _RFC3339_RE.match(raw)
    if not m:
        raise ValueError(f"not an RFC3339 timestamp: {raw!r}")
    year, month, day, hour, minute, second, frac, tz = m.groups()
    micro = int((frac or "0")[:6].ljust(6, "0"))
    if tz == "Z":
        tzinfo = timezone.utc
    else:
        sign = 1 if tz[0] == "+" else -1
        hh, mm = int(tz[1:3]), int(tz[4:6])
        if hh > 23 or mm > 59:
            raise ValueError(f"invalid time zone offset: {tz!r}")
        tzinfo = timezone(sign * timedelta(hours=hh, minutes=mm))
    return datetime(int(year), int(month), int(day), int(hour), int(minute), int(second), micro, tzinfo=tzinfo)


def b64encode(b: bytes | None) -> str | None:
    return None if b is None else base64.b64encode(b).decode("ascii")


def b64decode(s: str | None) -> bytes | None:
    return None if s is None else base64.b64decode(s)
