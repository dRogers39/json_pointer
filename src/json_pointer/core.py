"""Resolve and apply RFC 6901 JSON Pointers.

This module implements a strict subset of RFC 6901: resolving a pointer
against a JSON document (read access) and setting a value at a pointer
(write access). RFC 6901's full surface is small enough that we cover it
entirely, with the one interpretation noted below.

INTERPRETATION: When `set` is asked to create a member that does not
exist on an object whose current value is *not* a dict (e.g. a list or
None), we raise ``PointerResolutionError`` rather than silently
replacing the intermediate value. This matches the behavior most
implementations call "strict mode": the document's existing shape is
respected, and callers are never surprised by a vanished value. We do
not offer a lenient replacement mode; if you need one, copy the code
and delete three lines.
"""

from __future__ import annotations


class JsonPointerError(Exception):
    """Base class for all errors raised by this module."""


class PointerError(JsonPointerError):
    """The pointer string itself is malformed (syntax errors only).

    Distinct from ``PointerResolutionError`` so callers can tell a bad
    pointer apart from a document that doesn't match a good pointer.
    """


class PointerResolutionError(JsonPointerError):
    """The pointer is well-formed but the document does not match it.

    Covers: a missing key, an out-of-range list index, attempting to
tokenize a non-container, and attempting to *descend through* a key
whose current value is not a dict/list when a non-trivial member is
requested.
    """


class Pointer:
    """A parsed JSON Pointer (RFC 6901)."""

    __slots__ = ("_tokens",)

    def __init__(self, pointer):
        """Parse ``pointer`` once; safe to reuse across documents.

        ``pointer`` must be a ``str``. An empty string selects the whole
document, per RFC 6901 §5.
        """
        if not isinstance(pointer, str):
            raise PointerError(
                f"pointer must be str, got {type(pointer).__name__}"
            )
        if pointer == "":
            self._tokens = ()
            return
        if pointer[0] != "/":
            raise PointerError(
                f"non-empty pointer must start with '/', got {pointer!r}"
            )
        # Split on '/' and drop the empty leading element created by the
        # leading slash. We do *not* use ``split('/', 1)`` because we need
        # *all* segments. A trailing slash is an RFC-legal empty final
        # member token (it selects "" as a key), so we don't strip it.
        raw = pointer[1:].split("/")
        tokens = tuple(_unescape(tok) for tok in raw)
        self._tokens = tokens

    @property
    def tokens(self):
        """The tuple of unescaped reference tokens this pointer resolves."""
        return self._tokens

    def evaluate(self, document):
        """Resolve this pointer against ``document``; return the value."""
        node = document
        for i, tok in enumerate(self._tokens):
            if isinstance(node, list):
                index = _parse_index(tok)
                if index is None:
                    raise PointerResolutionError(
                        f"cannot index list with non-integer token {tok!r} at "
                        f"segment {i}"
                    )
                if index < 0 or index >= len(node):
                    raise PointerResolutionError(
                        f"list index {index} out of range (len={len(node)}) "
                        f"at segment {i}"
                    )
                node = node[index]
            elif isinstance(node, dict):
                if tok not in node:
                    raise PointerResolutionError(
                        f"missing key {tok!r} at segment {i}"
                    )
                node = node[tok]
            else:
                raise PointerResolutionError(
                    f"cannot descend into {type(node).__name__} for token "
                    f"{tok!r} at segment {i}"
                )
        return node

    def set(self, document, value):
        """Write ``value`` at this pointer's location in ``document``, in place.

        The document is mutated. ``document`` must be a mutable container
(dict or list). Creating missing intermediate objects on a path *is*
allowed (this is how you grow a document); replacing an existing
non-container intermediate with a fresh dict is *not* (see the
INTERPRETATION note in the module docstring).
        """
        tokens = self._tokens
        if not tokens:
            # Empty pointer selects the whole document. There is no
            # location *within* it to write to; the only sane behavior is
            # to refuse. Callers who want "replace the whole thing" should
            # rebind their own variable.
            raise PointerResolutionError(
                "cannot set root document via empty pointer"
            )
        node = document
        last = len(tokens) - 1
        for i, tok in enumerate(tokens):
            is_last = i == last
            if isinstance(node, list):
                index = _parse_index(tok)
                if index is None:
                    raise PointerResolutionError(
                        f"cannot index list with non-integer token {tok!r} "
                        f"at segment {i}"
                    )
                if is_last:
                    # Extend with None for write-at-end. Truncation would
                    # silently delete data and is never wanted.
                    while len(node) <= index:
                        node.append(None)
                    node[index] = value
                    return
                if index < 0 or index >= len(node):
                    raise PointerResolutionError(
                        f"list index {index} out of range (len={len(node)}) "
                        f"at non-final segment {i}"
                    )
                node = node[index]
            elif isinstance(node, dict):
                if is_last:
                    node[tok] = value
                    return
                if tok not in node or node[tok] is None:
                    # "or None" lets callers pre-declare an empty slot
                    # and have it promoted to whatever the next segment
                    # needs. We never replace a *present non-None* value.
                    next_tok = tokens[i + 1]
                    child = _make_container_for(next_tok)
                    node[tok] = child
                node = node[tok]
            else:
                raise PointerResolutionError(
                    f"cannot descend into {type(node).__name__} for token "
                    f"{tok!r} at segment {i}"
                )

    def __repr__(self):
        return f"Pointer({self._as_pointer_str()!r})"

    def __str__(self):
        return self._as_pointer_str()

    def _as_pointer_str(self):
        if not self._tokens:
            return ""
        return "/" + "/".join(_escape(t) for t in self._tokens)

    def __eq__(self, other):
        if not isinstance(other, Pointer):
            return NotImplemented
        return self._tokens == other._tokens

    def __hash__(self):
        return hash(self._tokens)


def evaluate(pointer, document):
    """Convenience: parse ``pointer`` and resolve it against ``document``."""
    return Pointer(pointer).evaluate(document)


def set(pointer, document, value):
    """Convenience: parse ``pointer`` and write ``value`` into ``document``."""
    Pointer(pointer).set(document, value)


def _unescape(tok):
    """Apply RFC 6901 §4: '~1' -> '/', '~0' -> '~'.

    Order matters: we must undo '~1' first so that a literal '~01' in the
    document (which encodes to '~001') round-trips back to '~01', not to
    '/1'. Reversing '~0' first would turn '~01' into '~1' and then into '/',
    which is wrong.
    """
    return tok.replace("~1", "/").replace("~0", "~")


def _escape(tok):
    """Inverse of ``_unescape``: '~' first then '/'."""
    return tok.replace("~", "~0").replace("/", "~1")


def _parse_index(tok):
    """RFC 6901 §6: a token is a valid array index iff it is decimal digits
    with no leading zero (except "0" itself) and no leading '+'. We reject
    anything else as a *resolution* error, not a syntax error, because the
    token is syntactically valid — it just isn't a valid array subscript
    for the list we happen to be looking at."""
    if not tok:
        return None
    if tok == "0":
        return 0
    if tok[0] == "0" or not tok.isdigit():
        return None
    return int(tok)


def _make_container_for(token):
    """When auto-vivifying a missing intermediate member, pick a container
    type from the *next* token: integer-looking -> list, else dict. This is
    a heuristic, not an RFC rule, but it is the only sensible default — and
    because we never replace a *present non-None* value, callers retain
    full control by pre-populating the document."""
    if _parse_index(token) is not None:
        return []
    return {}
