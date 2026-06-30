"""Property-based tests for per-backend SQL identifier quoting.

``quote_identifier`` is the single primitive that turns an arbitrary model/table
name into a SQL token, so its correctness is what keeps an identifier from
breaking out of its quotes and into the surrounding statement. These properties
assert two invariants across Hypothesis-generated identifiers, for both the
SQLite (double-quote) and MariaDB (backtick) dialects:

* **Faithfulness** -- an independent unquoter, modelling the SQL lexer's rules
  rather than re-stating the implementation, recovers the original identifier.
* **Containment** -- the quoted body holds the delimiter only in doubled pairs,
  so no input can terminate the identifier early (the injection-safety
  invariant).

The two together pin the full contract: the value survives intact *and* cannot
escape its quotes.
"""

from __future__ import annotations

from collections.abc import Callable

from hypothesis import settings
from hypothesis import strategies as st
from snektest import assert_eq, assert_raises, test, test_hypothesis

from snekql.mariadb.identifiers import quote_identifier as quote_mariadb
from snekql.sqlite.identifiers import quote_identifier as quote_sqlite

# The delimiter each dialect wraps an identifier in and escapes by doubling.
_SQLITE_DELIMITER = '"'
_MARIADB_DELIMITER = "`"

# Plain ``st.text()`` only occasionally draws a delimiter, so the escape path
# stays under-exercised. Mixing in a delimiter-rich alphabet guarantees runs of
# the quote characters -- the inputs most able to break the doubling logic.
_quote_heavy = st.text(st.sampled_from(['"', "`", "a", " ", "\n"]), max_size=12)
_identifiers = st.text() | _quote_heavy


def _unquote(quoted: str, delimiter: str) -> str:
    """Recover an identifier from its quoted form using the SQL lexer's rules.

    This is a deliberately separate implementation of the inverse: it asserts the
    output is wrapped in the delimiter and that every interior delimiter occurs
    as a doubled pair, then collapses those pairs. A lone (unescaped) delimiter in
    the body is malformed -- exactly the breakout a quoter must never emit -- and
    raises so the round-trip property fails loudly instead of silently diverging.
    """

    if len(quoted) < 2 or quoted[0] != delimiter or quoted[-1] != delimiter:
        msg = f"quoted identifier is not wrapped in {delimiter!r}: {quoted!r}"
        raise AssertionError(msg)
    body = quoted[1:-1]
    chars: list[str] = []
    index = 0
    while index < len(body):
        char = body[index]
        if char != delimiter:
            chars.append(char)
            index += 1
            continue
        # A delimiter in the body must be the first half of a doubled pair.
        if index + 1 >= len(body) or body[index + 1] != delimiter:
            msg = f"unescaped {delimiter!r} in quoted body: {quoted!r}"
            raise AssertionError(msg)
        chars.append(delimiter)
        index += 2
    return "".join(chars)


def _assert_round_trips(
    quote: Callable[[str], str], delimiter: str, identifier: str
) -> None:
    assert_eq(_unquote(quote(identifier), delimiter), identifier)


def _assert_contained(
    quote: Callable[[str], str], delimiter: str, identifier: str
) -> None:
    """No input can terminate the identifier early.

    After the wrapping delimiters are stripped and every doubled pair removed,
    the body must contain no remaining delimiter -- otherwise a crafted name
    could close the quote and append arbitrary SQL.
    """

    quoted = quote(identifier)
    assert_eq(quoted[0], delimiter)
    assert_eq(quoted[-1], delimiter)
    body = quoted[1:-1]
    assert_eq(body.replace(delimiter * 2, "").count(delimiter), 0)


@settings(deadline=None)
@test_hypothesis(_identifiers, mark="fast")
def sqlite_quoting_round_trips(identifier: str) -> None:
    """A double-quoted SQLite identifier unquotes back to the original."""

    _assert_round_trips(quote_sqlite, _SQLITE_DELIMITER, identifier)


@settings(deadline=None)
@test_hypothesis(_identifiers, mark="fast")
def sqlite_quoting_contains_the_identifier(identifier: str) -> None:
    """No SQLite identifier can break out of its double quotes."""

    _assert_contained(quote_sqlite, _SQLITE_DELIMITER, identifier)


@settings(deadline=None)
@test_hypothesis(_identifiers, mark="fast")
def mariadb_quoting_round_trips(identifier: str) -> None:
    """A backtick-quoted MariaDB identifier unquotes back to the original."""

    _assert_round_trips(quote_mariadb, _MARIADB_DELIMITER, identifier)


@settings(deadline=None)
@test_hypothesis(_identifiers, mark="fast")
def mariadb_quoting_contains_the_identifier(identifier: str) -> None:
    """No MariaDB identifier can break out of its backticks."""

    _assert_contained(quote_mariadb, _MARIADB_DELIMITER, identifier)


@settings(deadline=None)
@test_hypothesis(_identifiers, mark="fast")
def the_dialects_only_escape_their_own_delimiter(identifier: str) -> None:
    """Each dialect doubles only its own delimiter, leaving the other's
    delimiter as an ordinary body character.

    SQLite has no special meaning for a backtick and MariaDB none for a double
    quote, so neither character should be doubled by the other's quoter -- a
    cross-escape would corrupt a name that legitimately contains it.
    """

    assert_eq(
        quote_sqlite(identifier).count(_MARIADB_DELIMITER),
        identifier.count(_MARIADB_DELIMITER),
    )
    assert_eq(
        quote_mariadb(identifier).count(_SQLITE_DELIMITER),
        identifier.count(_SQLITE_DELIMITER),
    )


@test(mark="fast")
def unquote_rejects_malformed_tokens() -> None:
    """Meta-check on the test's own oracle.

    If ``_unquote`` accepted a lone interior delimiter or a missing wrapper, the
    round-trip property could pass against a broken quoter. Pin that each clearly
    malformed token is rejected, so the oracle stays strict enough to catch a
    breakout.
    """

    malformed = (
        'a"b',  # no wrapping delimiters at all
        '"a"b"',  # lone interior delimiter (a + " + b)
        '"abc',  # missing closing delimiter
        '"',  # single delimiter, too short to be a wrapped empty identifier
    )
    for token in malformed:
        with assert_raises(AssertionError):
            _ = _unquote(token, _SQLITE_DELIMITER)
