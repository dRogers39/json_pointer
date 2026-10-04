import unittest

from json_pointer import (
    Pointer,
    evaluate,
    set,
    JsonPointerError,
    PointerError,
    PointerResolutionError,
)


class TestParse(unittest.TestCase):

    def test_empty_pointer_is_root(self):
        p = Pointer("")
        self.assertEqual(p.tokens, ())

    def test_single_segment(self):
        self.assertEqual(Pointer("/foo").tokens, ("foo",))

    def test_multiple_segments(self):
        self.assertEqual(Pointer("/a/b/c").tokens, ("a", "b", "c"))

    def test_unescape_tilde1_slash(self):
        self.assertEqual(Pointer("/a~1b").tokens, ("a/b",))

    def test_unescape_tilde0_tilde(self):
        self.assertEqual(Pointer("/a~0b").tokens, ("a~b",))

    def test_unescape_order_preserves_tilde_slash_literal(self):
        # Document key "a~1b" encodes to "a~01b". Decoding must yield "a~1b".
        self.assertEqual(Pointer("/a~01b").tokens, ("a~1b",))

    def test_empty_key_segment(self):
        # A path like "/a//b" has an empty-string middle token, which is
        # a legal object key.
        self.assertEqual(Pointer("/a//b").tokens, ("a", "", "b"))

    def test_non_string_rejected(self):
        with self.assertRaises(PointerError):
            Pointer(123)  # noqa

    def test_missing_leading_slash_rejected(self):
        with self.assertRaises(PointerError):
            Pointer("foo")

    def test_pointer_str_roundtrips(self):
        for s in ["", "/foo", "/a/b/c", "/a~1b", "/a~0b"]:
            self.assertEqual(str(Pointer(s)), s)

    def test_pointer_repr(self):
        self.assertEqual(repr(Pointer("/foo")), "Pointer('/foo')")

    def test_equality_and_hash(self):
        a = Pointer("/x/y")
        b = Pointer("/x/y")
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertNotEqual(a, Pointer("/x/z"))


class TestEvaluate(unittest.TestCase):

    def test_root(self):
        doc = {"a": 1}
        self.assertIs(evaluate("", doc), doc)

    def test_object_key(self):
        self.assertEqual(evaluate("/foo", {"foo": 42}), 42)

    def test_nested_object(self):
        self.assertEqual(evaluate("/a/b/c", {"a": {"b": {"c": 7}}}), 7)

    def test_list_index(self):
        self.assertEqual(evaluate("/0", ["x", "y"]), "x")

    def test_nested_list(self):
        self.assertEqual(evaluate("/0/1", [[0, 1], [2, 3]]), 1)

    def test_mixed_list_object(self):
        self.assertEqual(evaluate("/0/name", [{"name": "joe"}]), "joe")

    def test_slash_in_key(self):
        self.assertEqual(evaluate("/a~1b", {"a/b": 9}), 9)

    def test_tilde_in_key(self):
        self.assertEqual(evaluate("/a~0b", {"a~b": 9}), 9)

    def test_empty_key(self):
        self.assertEqual(evaluate("/", {"": "empty"}), "empty")

    def test_missing_key_raises(self):
        with self.assertRaises(PointerResolutionError):
            evaluate("/missing", {})

    def test_list_index_out_of_range_raises(self):
        with self.assertRaises(PointerResolutionError):
            evaluate("/5", [1, 2, 3])

    def test_negative_index_not_supported(self):
        # RFC 6901 does not define negative indices; we treat "-1" as a
        # non-integer token and refuse to subscript the list.
        with self.assertRaises(PointerResolutionError):
            evaluate("/-1", [1, 2, 3])

    def test_non_integer_on_list_raises(self):
        with self.assertRaises(PointerResolutionError):
            evaluate("/x", [1, 2, 3])

    def test_descend_into_scalar_raises(self):
        with self.assertRaises(PointerResolutionError):
            evaluate("/a/b", {"a": 5})

    def test_descend_into_none_raises(self):
        with self.assertRaises(PointerResolutionError):
            evaluate("/a/b", {"a": None})

    def test_descend_into_list_with_string_key_raises(self):
        with self.assertRaises(PointerResolutionError):
            evaluate("/0/1", [{0: [1]}])


class TestSet(unittest.TestCase):

    def test_set_existing_object_key(self):
        doc = {"a": 1}
        set("/a", doc, 2)
        self.assertEqual(doc, {"a": 2})

    def test_set_existing_list_index(self):
        doc = [1, 2, 3]
        set("/1", doc, 9)
        self.assertEqual(doc, [1, 9, 3])

    def test_set_new_object_key(self):
        doc = {}
        set("/foo", doc, 7)
        self.assertEqual(doc, {"foo": 7})

    def test_set_new_nested_object_key_autovivifies(self):
        doc = {}
        set("/a/b/c", doc, 9)
        self.assertEqual(doc, {"a": {"b": {"c": 9}}})

    def test_set_list_append_via_end_index(self):
        doc = []
        set("/0", doc, "x")
        self.assertEqual(doc, ["x"])

    def test_set_list_extend_skipping(self):
        # Index 2 on a length-0 list: we fill [None, None, value]. This is
        # the documented "extend with None" behavior; we do not truncate.
        doc = []
        set("/2", doc, "z")
        self.assertEqual(doc, [None, None, "z"])

    def test_set_into_list_intermediate_must_exist(self):
        # Non-final segment pointing past the end of a list is an error,
        # because autovivifying "the next 5 elements" is a bad guess.
        doc = [1]
        with self.assertRaises(PointerResolutionError):
            set("/5/x", doc, 9)

    def test_set_descend_into_scalar_raises(self):
        doc = {"a": 5}
        with self.assertRaises(PointerResolutionError):
            set("/a/b", doc, 9)

    def test_set_does_not_replace_present_non_none_value(self):
        # The INTERPRETATION in the module docstring: a present non-None
        # intermediate is never silently replaced. Here '/a' is a list, and
        # '/a/b' wants to descend into it as a dict — that's an error, not
        # a quiet overwrite of the list.
        doc = {"a": [1, 2]}
        with self.assertRaises(PointerResolutionError):
            set("/a/b", doc, 9)

    def test_set_promotes_none_intermediate(self):
        # "or None" branch: a slot explicitly set to None *is* promoted.
        doc = {"a": None}
        set("/a/b", doc, 9)
        self.assertEqual(doc, {"a": {"b": 9}})

    def test_set_root_raises(self):
        doc = {}
        with self.assertRaises(PointerResolutionError):
            set("", doc, 9)

    def test_set_into_immutable_root_raises(self):
        # A tuple is not a list; we treat it as a non-container scalar.
        with self.assertRaises(PointerResolutionError):
            set("/0", (1, 2), 9)

    def test_set_object_key_containing_slash(self):
        doc = {}
        set("/a~1b", doc, 1)
        self.assertEqual(doc, {"a/b": 1})

    def test_set_object_key_containing_tilde(self):
        doc = {}
        set("/a~0b", doc, 1)
        self.assertEqual(doc, {"a~b": 1})

    def test_set_empty_string_key(self):
        doc = {}
        set("/", doc, 1)
        self.assertEqual(doc, {"": 1})

    def test_set_list_with_string_token_raises(self):
        doc = [1, 2]
        with self.assertRaises(PointerResolutionError):
            set("/x", doc, 9)


class TestErrors(unittest.TestCase):

    def test_error_hierarchy(self):
        self.assertTrue(issubclass(PointerError, JsonPointerError))
        self.assertTrue(issubclass(PointerResolutionError, JsonPointerError))


class TestPointerObjectReuse(unittest.TestCase):

    def test_parse_once_evaluate_many(self):
        p = Pointer("/a/b/c")
        d1 = {"a": {"b": {"c": 1}}}
        d2 = {"a": {"b": {"c": 2}}}
        self.assertEqual(p.evaluate(d1), 1)
        self.assertEqual(p.evaluate(d2), 2)

    def test_parse_once_set_many(self):
        p = Pointer("/x")
        d1 = {}
        d2 = {}
        p.set(d1, 1)
        p.set(d2, 2)
        self.assertEqual(d1, {"x": 1})
        self.assertEqual(d2, {"x": 2})


if __name__ == "__main__":
    unittest.main()
