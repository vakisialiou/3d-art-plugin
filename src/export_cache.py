"""Exports made this Blender session, by object key: a store that lacks a
glb this add-on already built (its file went an hour after nothing held it —
a review answered with Keep mine) gets it again without a second bake.
Memory only, least recently used first out.
"""

from collections import OrderedDict
from typing import Optional

from .resource_pack import Pack

_LIMIT_BYTES = 512 * 1024 * 1024

_packs: "OrderedDict[str, Pack]" = OrderedDict()
_bytes = 0


def get(key: str) -> Optional[Pack]:
    pack = _packs.get(key)
    if pack is not None:
        _packs.move_to_end(key)
    return pack


def put(key: str, pack: Pack) -> None:
    global _bytes
    previous = _packs.pop(key, None)
    if previous is not None:
        _bytes -= previous.size()
    _packs[key] = pack
    _bytes += pack.size()
    while _bytes > _LIMIT_BYTES and len(_packs) > 1:
        _, dropped = _packs.popitem(last=False)
        _bytes -= dropped.size()


def clear() -> None:
    global _bytes
    _packs.clear()
    _bytes = 0
