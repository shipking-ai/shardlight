"""Pure-python stand-in for pygame's ``rwobject`` module.

The wasm build of pygame-ce on the pygame-web CDN is missing ``pygame/rwobject``
(along with ``pygame/constants.py``), while its own ``pygame/__init__.py``
imports ``encode_string`` and ``encode_file_path`` from it.  These are the
documented semantics of the compiled module, taken from pygame's own type
stubs: strings are encoded to bytes, everything else is passed through.
"""
from __future__ import annotations

from typing import Any, Optional, Type


def encode_string(
    obj: Optional[Any],
    encoding: Optional[str] = "unicode_escape",
    errors: Optional[str] = "backslashreplace",
    etype: Optional[Type[Exception]] = UnicodeEncodeError,
) -> bytes:
    if isinstance(obj, str):
        try:
            return obj.encode(encoding or "utf-8", errors or "strict")
        except UnicodeEncodeError as exc:
            if etype is None:
                raise
            raise etype(str(exc)) from exc
    return obj  # type: ignore[return-value]


def encode_file_path(
    obj: Any,
    etype: Optional[Type[Exception]] = UnicodeEncodeError,
) -> bytes:
    if isinstance(obj, str):
        try:
            return obj.encode("utf-8")
        except UnicodeEncodeError as exc:
            if etype is None:
                raise
            raise etype(str(exc)) from exc
    return obj  # type: ignore[return-value]
