"""Unit tests for the row conversion helpers.

These tests exercise :mod:`justorm._fetch` directly, without touching a
database or a driver.  They cover the four accepted ``format`` values
(``None``, ``tuple``, ``dict``, ``namedtuple``) and the error path for
unknown values.

The integration tests for the cursor-level ``fetch*`` methods live in
the per-driver test modules; here we only check the conversion logic.
"""

from __future__ import annotations

from collections import namedtuple

import pytest

from justorm import JustormValueError
from justorm._fetch import (
    FORMATS,
    convert_row,
    convert_rows,
    field_names,
)


# A description as returned by most DB-API drivers: a sequence of
# 7-tuples whose first element is the column name.
DESCRIPTION = (
    ("id", None, None, None, None, None, None),
    ("name", None, None, None, None, None, None),
    ("age", None, None, None, None, None, None),
)


# ---------------------------------------------------------------------------
# field_names
# ---------------------------------------------------------------------------


class TestFieldNames:
    def test_none_description(self):
        assert field_names(None) == []

    def test_empty_description(self):
        assert field_names(()) == []

    def test_names(self):
        assert field_names(DESCRIPTION) == ["id", "name", "age"]


# ---------------------------------------------------------------------------
# convert_row
# ---------------------------------------------------------------------------


class TestConvertRow:
    def test_none_row(self):
        # A missing row is always ``None``, whatever the format.
        assert convert_row(None, DESCRIPTION, None) is None
        assert convert_row(None, DESCRIPTION, tuple) is None
        assert convert_row(None, DESCRIPTION, dict) is None
        assert convert_row(None, DESCRIPTION, namedtuple) is None

    def test_no_format_returns_row_unchanged(self):
        row = (1, "Alice", 30)
        assert convert_row(row, DESCRIPTION, None) is row

    def test_tuple(self):
        row = [1, "Alice", 30]
        out = convert_row(row, DESCRIPTION, tuple)
        assert out == (1, "Alice", 30)
        assert isinstance(out, tuple)

    def test_dict(self):
        row = (1, "Alice", 30)
        out = convert_row(row, DESCRIPTION, dict)
        assert out == {"id": 1, "name": "Alice", "age": 30}

    def test_namedtuple(self):
        row = (1, "Alice", 30)
        out = convert_row(row, DESCRIPTION, namedtuple)
        assert out.id == 1
        assert out.name == "Alice"
        assert out.age == 30
        # Field access by index also works.
        assert out[0] == 1

    def test_namedtuple_is_cached(self):
        from justorm._fetch import _namedtuple_class

        a = _namedtuple_class(["id", "name"])
        b = _namedtuple_class(["id", "name"])
        assert a is b

    def test_unknown_format_rejected(self):
        with pytest.raises(JustormValueError):
            convert_row((1, "Alice", 30), DESCRIPTION, list)

    def test_unknown_format_rejected_with_string(self):
        with pytest.raises(JustormValueError):
            convert_row((1, "Alice", 30), DESCRIPTION, "dict")


# ---------------------------------------------------------------------------
# convert_rows
# ---------------------------------------------------------------------------


class TestConvertRows:
    def test_empty(self):
        assert convert_rows([], DESCRIPTION, None) == []
        assert convert_rows([], DESCRIPTION, tuple) == []
        assert convert_rows([], DESCRIPTION, dict) == []
        assert convert_rows([], DESCRIPTION, namedtuple) == []

    def test_no_format_returns_list_of_rows(self):
        rows = [(1, "Alice"), (2, "Bob")]
        out = convert_rows(rows, DESCRIPTION[:2], None)
        assert out == [(1, "Alice"), (2, "Bob")]
        assert isinstance(out, list)

    def test_tuple(self):
        rows = [(1, "Alice"), (2, "Bob")]
        out = convert_rows(rows, DESCRIPTION[:2], tuple)
        assert out == [(1, "Alice"), (2, "Bob")]
        assert all(isinstance(r, tuple) for r in out)

    def test_dict(self):
        rows = [(1, "Alice", 30), (2, "Bob", 25)]
        out = convert_rows(rows, DESCRIPTION, dict)
        assert out == [
            {"id": 1, "name": "Alice", "age": 30},
            {"id": 2, "name": "Bob", "age": 25},
        ]

    def test_namedtuple(self):
        rows = [(1, "Alice", 30), (2, "Bob", 25)]
        out = convert_rows(rows, DESCRIPTION, namedtuple)
        assert out[0].name == "Alice"
        assert out[1].age == 25

    def test_none_row_inside_list(self):
        # Some drivers yield ``None`` inside a result set (for example
        # when a row was deleted concurrently); we pass it through.
        rows = [(1, "Alice"), None, (2, "Bob")]
        out = convert_rows(rows, DESCRIPTION[:2], dict)
        assert out == [
            {"id": 1, "name": "Alice"},
            None,
            {"id": 2, "name": "Bob"},
        ]

    def test_unknown_format_rejected_on_empty_input(self):
        # A bad format must surface even when there are no rows.
        with pytest.raises(JustormValueError):
            convert_rows([], DESCRIPTION, list)


# ---------------------------------------------------------------------------
# namedtuple specifics
# ---------------------------------------------------------------------------


class TestNamedtuple:
    def test_duplicate_columns_are_renamed(self):
        description = (
            ("id",),
            ("name",),
            ("id",),
            ("name",),
        )
        row = (1, "Alice", 2, "Bob")
        out = convert_row(row, description, namedtuple)
        # ``rename=True`` replaces the invalid names with ``_0``, ``_1``,
        # etc.
        assert out.id == 1
        assert out.name == "Alice"
        assert out._2 == 2
        assert out._3 == "Bob"

    def test_field_names_from_dict(self):
        out = convert_row((1, "Alice"), DESCRIPTION[:2], dict)
        assert set(out.keys()) == {"id", "name"}

    def test_no_description_returns_empty_dict(self):
        # Without a description there are no column names; the dict is
        # empty rather than an error.
        out = convert_row((1, "Alice"), None, dict)
        assert out == {}


# ---------------------------------------------------------------------------
# FORMATS constant
# ---------------------------------------------------------------------------


class TestFormatsConstant:
    def test_formats(self):
        assert set(FORMATS) == {tuple, dict, namedtuple}
