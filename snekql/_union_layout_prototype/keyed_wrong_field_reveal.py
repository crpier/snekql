"""One selector must not choose different fields for different operands."""

from typing import reveal_type

from keyed import Fields, integer, project, text

left = project(Fields(event_id=integer(), title=text()))
right = project(Fields(event_id=integer(), title=text()))


def probe(choose_id: bool) -> None:
    """A runtime branch cannot change the selected output identity."""
    reveal_type(
        left.union_all(right).column(
            lambda fields: fields.event_id if choose_id else fields.title
        )
    )
