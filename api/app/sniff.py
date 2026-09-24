"""A small subset of Go's http.DetectContentType, used only when an upload
arrives without a Content-Type on its multipart part (browsers always send
one, so this is a fallback)."""

_SIGNATURES = [
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
    (b"PK\x03\x04", "application/zip"),
    (b"\x1f\x8b\x08", "application/x-gzip"),
    (b"\x00\x00\x01\x00", "image/x-icon"),
]


def detect_content_type(data: bytes) -> str:
    head = data[:512]
    for sig, ctype in _SIGNATURES:
        if head.startswith(sig):
            return ctype
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    stripped = head.lstrip(b"\t\n\x0c\r ")
    lowered = stripped[:14].lower()
    if lowered.startswith((b"<!doctype html", b"<html", b"<head", b"<body")):
        return "text/html; charset=utf-8"
    if stripped.startswith(b"<?xml"):
        return "text/xml; charset=utf-8"
    # Go treats data with no binary bytes as text/plain.
    if not any(b < 0x20 and b not in (0x09, 0x0A, 0x0C, 0x0D, 0x1B) for b in head):
        return "text/plain; charset=utf-8"
    return "application/octet-stream"
