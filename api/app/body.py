"""Strict JSON request-body decoding that behaves like the Go API's
decodeJSON (json.Decoder with DisallowUnknownFields decoding into a struct):

- the body must start with one JSON value (anything after it is ignored, as
  json.Decoder.Decode only reads the first value); empty/invalid -> error
- the value must be an object (or null, which Go decodes as "no fields")
- unknown fields are rejected; field names match case-insensitively, as
  encoding/json does
- each field's JSON type must match its declared kind; a JSON null leaves a
  plain field at its zero value and a pointer field unset (None)

Any violation raises ApiError(400, "invalid_body", ...), the same response
every Go handler returns for a decode error.
"""

from __future__ import annotations

import json
from typing import Any

from .errors import ApiError

# Field kinds:
STR = "string"          # Go string      - null -> ""
BOOL = "bool"           # Go bool        - null -> False
OPT_STR = "*string"     # Go *string     - null/absent -> None
OPT_STR_LIST = "*[]string"  # Go *[]string - null/absent -> None

_ZERO = {STR: "", BOOL: False, OPT_STR: None, OPT_STR_LIST: None}

INVALID_BODY = ApiError(400, "invalid_body", "request body must be valid JSON")


def _check(kind: str, value: Any) -> Any:
    if value is None:
        return _ZERO[kind]
    if kind in (STR, OPT_STR):
        if not isinstance(value, str):
            raise INVALID_BODY
        return value
    if kind == BOOL:
        if not isinstance(value, bool):
            raise INVALID_BODY
        return value
    if kind == OPT_STR_LIST:
        if not isinstance(value, list):
            raise INVALID_BODY
        out = []
        for item in value:
            if item is None:
                out.append("")
            elif isinstance(item, str):
                out.append(item)
            else:
                raise INVALID_BODY
        return out
    raise AssertionError(f"unknown field kind {kind}")


def decode(raw: bytes, schema: dict[str, str]) -> dict[str, Any]:
    """Decode raw into {field: value} for every field in schema (missing
    fields get their zero value). Raises ApiError on any decode error."""
    try:
        text = raw.decode("utf-8")
        value, _ = json.JSONDecoder().raw_decode(text.lstrip())
    except (UnicodeDecodeError, ValueError):
        raise INVALID_BODY

    out = {name: _ZERO[kind] for name, kind in schema.items()}
    if value is None:
        return out
    if not isinstance(value, dict):
        raise INVALID_BODY

    for key, v in value.items():
        name = key if key in schema else next((n for n in schema if n.lower() == key.lower()), None)
        if name is None:
            raise INVALID_BODY  # DisallowUnknownFields
        out[name] = _check(schema[name], v)
    return out
