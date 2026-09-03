"""Private static states describing whether query state can be executed."""

from __future__ import annotations


class _IncompleteQuery:
    """Typing-only marker for state guaranteed to fail Query Compilation."""


class _ExecutableQuery:
    """Typing-only marker for state that may cross a Query Runtime seam."""


class _EmptyUpdate(_IncompleteQuery):
    """Update state with neither assignment nor row scope."""


class _AssignedUpdate(_IncompleteQuery):
    """Update state with assignments but no row scope."""


class _ScopedUpdate(_IncompleteQuery):
    """Update state with row scope but no assignments."""


class _ExecutableUpdate(_ExecutableQuery):
    """Update state with assignments and row scope."""
