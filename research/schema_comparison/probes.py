"""Independent raw SQL specifications, each run against the same seed."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Probe:
    """One mutation, expected enforcement, and optional observable rows."""

    name: str
    sql: tuple[str, ...]
    reject: bool = False
    query: str | None = None
    expected: tuple[tuple[object, ...], ...] | None = None


SEED = (
    "INSERT INTO users (id,email,status) VALUES (1,'alice','active'),(2,'bob','active')",
    "INSERT INTO profiles (user_id,bio) VALUES (2,NULL)",
    "INSERT INTO teams (id,name) VALUES (1,'one'),(2,'two')",
    "INSERT INTO memberships (team_id,user_id,alias) VALUES (1,1,'owner')",
)

PROBES = (
    Probe(
        "duplicate_email",
        ("INSERT INTO users (id,email,status) VALUES (3,'alice','active')",),
        reject=True,
    ),
    Probe(
        "required_email",
        ("INSERT INTO users (id,status) VALUES (3,'active')",),
        reject=True,
    ),
    Probe(
        "null_email",
        ("INSERT INTO users (id,email,status) VALUES (3,NULL,'active')",),
        reject=True,
    ),
    Probe(
        "nullable_nickname",
        ("INSERT INTO users (id,email,status,nickname) VALUES (3,'c','active',NULL)",),
    ),
    Probe(
        "python_default_is_not_server_default",
        ("INSERT INTO users (id,email) VALUES (3,'c')",),
        reject=True,
    ),
    Probe(
        "generated_id",
        ("INSERT INTO users (email,status) VALUES ('c','active')",),
        query="SELECT id FROM users WHERE email='c'",
        expected=((3,),),
    ),
    Probe(
        "duplicate_profile", ("INSERT INTO profiles (user_id) VALUES (2)",), reject=True
    ),
    Probe(
        "orphan_profile", ("INSERT INTO profiles (user_id) VALUES (999)",), reject=True
    ),
    Probe(
        "profile_cascade",
        ("DELETE FROM users WHERE id=2",),
        query="SELECT COUNT(*) FROM profiles",
        expected=((0,),),
    ),
    Probe("membership_restrict", ("DELETE FROM users WHERE id=1",), reject=True),
    Probe(
        "team_cascade",
        ("DELETE FROM teams WHERE id=1",),
        query="SELECT COUNT(*) FROM memberships",
        expected=((0,),),
    ),
    Probe(
        "duplicate_membership",
        ("INSERT INTO memberships VALUES (1,1,'different')",),
        reject=True,
    ),
    Probe(
        "tenant_scoped_alias",
        ("INSERT INTO memberships VALUES (1,2,'owner')",),
        reject=True,
    ),
    Probe("alias_in_other_team", ("INSERT INTO memberships VALUES (2,2,'owner')",)),
    Probe(
        "orphan_membership",
        ("INSERT INTO memberships VALUES (999,2,'new')",),
        reject=True,
    ),
    Probe(
        "null_composite_key",
        ("INSERT INTO memberships VALUES (NULL,2,'new')",),
        reject=True,
    ),
    Probe(
        "wide_id",
        ("INSERT INTO users (id,email,status) VALUES (2147483648,'c','active')",),
    ),
    Probe(
        "blob_in_text",
        ("INSERT INTO users (id,email,status) VALUES (3,X'6162','active')",),
    ),
    # Diagnostic probes have no common cross-track expectation.
    Probe(
        "case_distinct_email",
        ("INSERT INTO users (id,email,status) VALUES (3,'ALICE','active')",),
    ),
    Probe(
        "id_reuse",
        (
            "DELETE FROM users WHERE id=2",
            "INSERT INTO users (email,status) VALUES ('c','active')",
        ),
        query="SELECT id FROM users WHERE email='c'",
    ),
    Probe(
        "long_email",
        (
            "INSERT INTO users (id,email,status) VALUES (3,'"
            + "x" * 256
            + "','active')",
        ),
    ),
)
