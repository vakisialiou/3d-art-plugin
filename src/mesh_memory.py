"""Float data of the modifier-evaluated meshes keyed this session. A mesh
with the same topology, attribute names and integer data as a remembered
one, and float arrays each within 8 ULPs (of the array's largest magnitude)
of it, is hashed with the remembered floats, so its object key doesn't change
with rounding; anything larger is a new mesh, so a real edit still changes
the key.

Evaluation isn't bit-stable: Bevel averages each group of UV corners in the
iteration order of a pointer-keyed set (bevel_merge_uvs, bmesh_bevel.cc), so
the same inputs give UVs an ULP apart from one evaluation to the next. Copies
of one mesh evaluate separately and differ the same way; a copy takes the
floats of the first one remembered, so they share a key and travel once. An
edit undone finds its earlier floats again.

Memory only, least recently used first out.
"""

import hashlib
import itertools
from collections import OrderedDict
from typing import Optional

import numpy as np

# Rounding allowance per float array, in ULPs of its largest magnitude.
_ULPS = 8
_LIMIT_BYTES = 256 * 1024 * 1024


class _Floats:
    """One remembered float set; its sums reject a different mesh cheaply."""

    __slots__ = ("group", "arrays", "sums", "limits", "nbytes")

    def __init__(self, group: bytes, arrays: list):
        self.group = group
        self.arrays = arrays
        self.sums = [float(array.sum(dtype=np.float64)) for array in arrays]
        self.limits = [_ULPS * float(np.spacing(np.abs(array).max())) if array.size else 0.0 for array in arrays]
        self.nbytes = sum(array.nbytes for array in arrays)

    def matches(self, other: "_Floats") -> bool:
        for new, old, new_sum, old_sum, limit in zip(other.arrays, self.arrays, other.sums, self.sums, self.limits):
            if abs(new_sum - old_sum) > limit * new.size:
                return False
            if np.array_equal(new.view(np.uint32), old.view(np.uint32)):
                continue  # bit for bit, NaNs included
            if not np.all(np.abs(new.astype(np.float64) - old) <= limit):
                return False
        return True


_sets: "OrderedDict[int, _Floats]" = OrderedDict()  # by number, least recently used first
_groups: dict = {}  # group → {set number: None}
_last: dict = {}  # object → number of the set it was hashed with last, tried first
_numbers = itertools.count()
_bytes = 0


def recall(parts: list, owner: str) -> list:
    """`parts` (bytes and float32 arrays, in hashing order) of `owner`'s
    mesh, with the arrays of a remembered mesh whose bytes are the same and
    whose floats are within rounding of these; else `parts` as given, now
    remembered."""
    exact = hashlib.sha256()
    arrays = []
    for part in parts:
        if isinstance(part, np.ndarray):
            arrays.append(part)
            exact.update(f"floats:{part.size}\0".encode())
        else:
            exact.update(part)
    current = _Floats(exact.digest(), arrays)
    number = _find(current, owner)
    if number is None:
        number = _add(current)
    _sets.move_to_end(number)
    _last[owner] = number
    found = _sets[number]
    if found is current:
        return parts
    swapped = iter(found.arrays)
    return [next(swapped) if isinstance(part, np.ndarray) else part for part in parts]


def clear() -> None:
    global _bytes
    _sets.clear()
    _groups.clear()
    _last.clear()
    _bytes = 0


def _find(current: _Floats, owner: str) -> Optional[int]:
    last = _last.get(owner)
    candidates = _groups.get(current.group, {})
    if last in candidates and _sets[last].matches(current):
        return last
    for number in candidates:
        if number != last and _sets[number].matches(current):
            return number
    return None


def _add(floats: _Floats) -> int:
    global _bytes
    number = next(_numbers)
    _sets[number] = floats
    _groups.setdefault(floats.group, {})[number] = None
    _bytes += floats.nbytes
    while _bytes > _LIMIT_BYTES and len(_sets) > 1:
        dropped_number, dropped = _sets.popitem(last=False)
        _bytes -= dropped.nbytes
        members = _groups[dropped.group]
        del members[dropped_number]
        if not members:
            del _groups[dropped.group]
    return number
