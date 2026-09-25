"""All three review files expose the agreed situations in the same order."""

from pathlib import Path
from re import MULTILINE, findall

from anyio import to_thread
from snektest import assert_eq, test


@test(mark="fast")
async def review_sections_match_the_agreed_order() -> None:
    directory = Path(__file__).parent
    nested = await to_thread.run_sync((directory / "nested.py").read_text)
    body = await to_thread.run_sync((directory / "body.py").read_text)
    headings = findall(r"^# (\d\d\. .+)$", nested, flags=MULTILINE)
    assert_eq(len(headings), 12)
    assert_eq(headings, findall(r"^# (\d\d\. .+)$", body, flags=MULTILINE))
    dual = await to_thread.run_sync((directory / "dual.py").read_text)
    assert_eq(headings, findall(r"^# (\d\d\. .+)$", dual, flags=MULTILINE))


@test(mark="fast")
def function_local_self_reference_has_identical_scaffold() -> None:
    from snektest import assert_in

    from scratchpad.paired_situations import body, nested

    nested_schema = nested.local_comment_schema()
    assert_in('REFERENCES "local_comments"', nested_schema)
    assert_eq(nested_schema, body.local_comment_schema())
