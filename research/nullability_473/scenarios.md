# Scenario-first comparison: SQL nullability and construction

2026-10-26, #473. **Design examples, not executable templates or native evidence.**
See [the report](README.md) for source references, checked subsets and limitations.

- **A — current:** one Logical Type; SQL nullability must agree with None membership.
- **B — independent schema, one domain:** explicit nullable= describes SQL; one
  application domain is enforced on construction and successful reads. Incompatible
  data may fail materialization. This policy is not implemented.
- **C — independent schema, split domains:** research spelling Col[Input, Read=Input]
  / GenCol[Input, Read=Input]. Only a small native typing prototype exists, not the
  runtime implementation. Nullable read widening is not arbitrary codec conversion.

Text/Integer and Col/GenCol below mean the respective candidate declarations;
qualified namespaces and model boilerplate are omitted for readability. In A/B,
server markers still use current syntax; C's research Text uses separate defaults
with explicit pending. This is **not a defaults-spelling competition or a claim
that C needs more verbosity inherently**. The defaults decision remains open.

## 1. Required non-null value, NOT NULL schema

```python
# A
value: Col[str] = Text()
# B
value: Col[str] = Text(nullable=False)
# C: one-argument shorthand keeps equal domains
value: Col[str] = Text(nullable=False)
```

All: omission rejected, None rejected, Pending/Row str. SQL NOT NULL, no default.
This basic case needs neither a required flag nor separate domain arguments.
B/C omission of nullable= remains a separate policy decision.

## 2. Required nullable value, nullable schema

```python
# A
value: Col[str | None] = Text()
# B
value: Col[str | None] = Text(nullable=True)
# C
value: Col[str | None] = Text(nullable=True)
```

All: omission rejected, explicit None accepted; Pending/Row str or None. SQL
nullable, no default. Externally stored NULL is a compatible value. A nullable
field is not an omittable constructor argument (including nullable FKs, #236).

## 3. Python None default

```python
# A
value: Col[str | None] = Text(default=None)
# B
value: Col[str | None] = Text(nullable=True, default=None)
# C
value: Col[str | None] = Text(nullable=True, default=None)
```

All: omission supplies Python None; explicit None accepted. Pending/Row str or
None. SQL nullable **without a declared server default**. INSERT binds NULL.
Verification must not invent DEFAULT NULL from the Python default.

## 4. Non-None Python default or factory, nullable schema

```python
# A
value: Col[str | None] = Text(default="client")
# B
value: Col[str | None] = Text(nullable=True, default="client")
# C: application wants to prohibit explicit None, while accepting NULL on reads
value: Col[str, str | None] = Text(nullable=True, default="client")
```

All omit the constructor argument successfully and bind a Python value, not a
SQL default. A/B accept an explicit None; C rejects it on input but can read None.
A/B Pending type str or None, C Pending str; all Row types str or None.

A factory has the same domains but its own per-construction evaluation contract.
Native producer signatures and arity are checked; evaluation/frequency is not.
For C, a Python None default is incompatible with Input=str even though Read
admits None. That differs from SQL DEFAULT NULL, which acts after omission.

## 5. Nullable brownfield column, non-null application values

```python
# A: only one of these intentions can be kept
value: Col[str | None] = Text()  # accurately nullable, but input/read admit None
# Col[str] = Text(nullable=True) fails current runtime declaration checks.

# B: strict application domain
value: Col[str] = Text(nullable=True)

# C: strict construction, nullable successful reads
value: Col[str, str | None] = Text(nullable=True)
```

| Observation | A, nullable declaration | B, strict subset | C, wider reads |
| --- | --- | --- | --- |
| Keyword omitted | Reject | Reject | Reject |
| Constructor receives None | Accept | Reject | Reject |
| Pending value type | str or None | str | str |
| SQL permits another writer's NULL | Yes | Yes | Yes |
| Read actual NULL | Return None | **Raise materialization error** | Return None |
| Successfully returned Row value type | str or None | str | str or None |
| Verification of matching nullable schema | Match | Match | Match |

B requires new logical-null checks; simply allowing the flag in today's code
would return None into a str Row and be unsound. Neither B nor C silently filters
rows, changes the database, or claims to prevent external writers storing NULL.

## 6. Python None against SQL NOT NULL

```python
# A rejects this at class definition.
# B/C need an explicit write-policy decision, not a boolean-name substitution.
value: Col[str | None] = Text(nullable=False)
```

For ordinary scalars, None currently encodes to SQL NULL. A safe default is not
to promise this value is writable. Choices to investigate: reject the declaration,
reject that input before any write, or support an explicit transformation.
Deferring accidentally to a DB constraint error is not an elegance improvement.

Read type may legitimately be broader than physical NULL permission when a codec
maps a non-NULL wire value to a logical None. That is a different case, not proof
that plain None input is safe to write. No transformation policy is selected or
validated here. `required=True` would only demand a keyword, not fix its value.

## 7. Server literal and SQL DEFAULT NULL

```python
# A: server literal
value: GenCol[str | None] = Text(default=LiteralDefault("server"))
# B: strict non-null application values, nullable SQL schema
value: GenCol[str] = Text(nullable=True, default=LiteralDefault("server"))
# C: strict inputs, nullable read; explicit pending retained in this probe
value: GenCol[str, str | None] = Text(
    nullable=True, default=PENDING_GENERATION, server_default="server"
)
```

Omission intends pending, INSERT omits the column, SQL supplies the literal.
A accepts explicit None and binds NULL; B/C reject None on input. A/C read external
NULL as None; B must reject it. Pending includes the marker; Row never includes it.

For C, replacing server_default="server" with server_default=None declares SQL
DEFAULT NULL. Omission can then produce a Row None **despite input None being
rejected**. This is checked statically as a contract, not executed SQL behavior.
For B's generated non-null Read domain, automatic DEFAULT NULL generation would
produce a value the application cannot materialize; the narrow prototype rejects
that combination. However, describing DEFAULT NULL **only as a fallback for other
writers** can be legitimate under B's strict-subset policy. Such rows fail reads
intentionally. Do not blanket-reject schema fidelity merely because an application
does not decode the whole database domain. Python defaults must fit the input
policy; generation requested by this application must respect its chosen read
contract. Physical SQL default compatibility is a separate question.

UTC clocks follow the same ownership distinction but need temporal/storage
compatibility and nullable-clock controls; this first prototype does not cover
clock producers. Identity is separate from SQL DEFAULT.

## 8. Required SQL fallback and defaultless generated inputs

```python
# Existing split research / current nullability prototype, not installed syntax:
value: Col[str, str | None] = Text(nullable=True, server_default="server")

# Generated shape does not independently grant omission:
value: GenCol[str] = Text()
```

The first requires a Python value yet declares a SQL fallback for other writers.
The registered producer's absence of a Python default preserves requiredness;
accepted SQL compatibility gaps are documented in the report.

The second requires a concrete value or explicit pending sentinel. GenCol controls
state-dependent value types, not whether an input has a default. Requesting
generation does not establish that a suitable trigger/default/identity exists.
This investigation does not adopt required=True or solve shorter common server
omission under this contract.

## 9. LEFT JOIN versus base-column nullability

```python
select(Parent).left_join(Child, on=...)  # tuple[Parent[Row], Child[Row] | None]
```

An unmatched Child is None as a **whole row**, even when its base schema is NOT
NULL. A matched Child may independently contain nullable fields. For all-nullable
physical payloads, a hidden presence witness distinguishes a matched all-NULL
row from no row (`snekql/_materialization_shape.py`). Keep that physical-schema
fact even if B's application domain is strict.

C's native imported-consumer check preserves the existing whole-model join type.
Projection LEFT JOIN remains unsupported; no new projection contract is claimed.
Scalar subqueries and empty aggregates can also return NULL independently of the
base column's nullability.

## 10. Keys, codecs and backend/catalog differences

- Required nullable FK input remains different from default=None. SET NULL needs
  nullable, non-PK local columns. Under B it can deliberately create unreadable
  application data; under C a nullable read domain can accept it. FK-specific
  declaration/target overloads are not covered by this prototype.
- SQLite integer-rowid/STRICT PK metadata differs from other and composite PKs;
  MariaDB PK parts enforce NOT NULL. Do not infer Row=None from a catalog bit or
  overload a constructor-required flag to compensate for those differences.
- Nested JSON None is not column nullability. JSON wire text "null" and driver
  SQL NULL take different paths. Python None currently encodes to SQL NULL before
  JSON encoding; a non-NULL representation requires a separate codec decision.
- SQLite distinguishes absence of a default from DEFAULT NULL. MariaDB may
  normalize nullable implicit/explicit NULL and report explicitness unchecked.
- All designs must feed the same physical nullability to scaffold and expected
  verification shape. A matching schema says nothing about data decoding success.
  No schema declaration, verification or investigation silently alters tables.
