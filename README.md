# json-pointer

A small, zero-dependency Python library for resolving and applying RFC 6901
JSON Pointers against plain Python dicts and lists.

```python
from json_pointer import Pointer, evaluate, set

doc = {"a": [{"b": 1}, {"b": 2}]}

# Resolve
assert evaluate("/a/1/b", doc) == 2

# Apply in place
set("/a/0/b", doc, 99)
assert doc["a"][0]["b"] == 99

# Reuse a parsed pointer
p = Pointer("/a/1/b")
assert p.evaluate(doc) == 2
p.set(doc, 7)
assert doc["a"][1]["b"] == 7
```

## Why this exists

The standard library has no JSON Pointer type. When you need one you usually
need exactly one — small, inspectable, and free of a transitive dependency
chain. This is that one. It covers the whole of RFC 6901's *pointer* surface
(resolution and set) and nothing else: no patching (RFC 6902), no relative
pointers, no schema anchors.

The trade-off is strictness over convenience. `set` will create missing
intermediate object members, but it will **not** silently replace an existing
non-`None` intermediate value with a fresh container to keep descending. If
`/a` is a list and you call `set("/a/b", doc, 1)`, you get a
`PointerResolutionError`, not a quiet overwrite. The same applies to descending
through a scalar. A present `None` *is* promoted (this lets callers pre-declare
empty slots explicitly); a present list/dict/scalar is not.

## The awkward edge

Array-index tokens. RFC 6901 §6 says a token is a valid array index only when
it is decimal digits with no leading zero (except `"0"` itself) and no leading
`+`. A token like `"x"` or `"-1"` or `"01"` is *syntactically valid* but not a
list subscript, so it is a **resolution** error (`PointerResolutionError`),
not a **syntax** error (`PointerError`). The split matters: `PointerError`
means the pointer string is garbage; `PointerResolutionError` means a good
pointer met a document it doesn't fit.

Two more things worth knowing: a trailing slash is legal and denotes an empty
final key (so `/a/` selects the member `""` under `"a"`); and the empty pointer
`""` selects the whole document — `evaluate("", doc)` returns `doc` itself,
while `set("", doc, x)` raises because there is no location *inside* the root
to write to.

## Exports

- `Pointer(pointer_str)` — parse once, reuse against many documents.
  - `.tokens` — tuple of unescaped reference tokens.
  - `.evaluate(document)` — read access.
  - `.set(document, value)` — write access, in place.
  - `__str__`, `__repr__`, `__eq__`, `__hash__`.
- `evaluate(pointer, document)` — convenience wrapper.
- `set(pointer, document, value)` — convenience wrapper.
- `JsonPointerError` — base exception.
- `PointerError` — bad pointer syntax.
- `PointerResolutionError` — good pointer, document mismatch.

Python 3.8+. Standard library only. Tested with `python -m unittest discover
-s tests` and `PYTHONPATH=src`.

## Design notes

The window stores values eagerly rather than keeping running aggregates. Running
sums drift with floating point over long streams, and recomputing from a small
buffer is cheap enough that the drift is not worth the speed.

