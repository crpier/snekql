# snekql schema and query language

Vocabulary for the distinction between querying stored data, managing schema changes and
establishing application readiness.

## Language

**Query Mapping**:
The relationship between an application's logical values and the stored fields used by its
queries and writes. A mapping conveys neither schema-management authority nor ownership.

**Migration Ownership**:
A migration chain's explicitly selected authority over named physical schema facts.
Ownership is independent of which tables an application maps or can access.
_Avoid_: Model ownership, query ownership

**Recorded State**:
The declared managed schema facts at a point in a migration chain, rather than an observation
of a live database or a declaration of current application requirements.

**Historical Query Contract**:
The field and value expectations for queries authored at a named intermediate recorded state.
It is not a promise that today's codecs can interpret historical data.

**Execution Package**:
The reviewed historical intent and frozen execution inputs for one migration transition,
independent of current application declarations.

**Prepared Plan**:
A target-specific execution plan bound to the observations and choices under which an
execution package was prepared. It is not interchangeable with the target-independent package.

**Execution Receipt**:
Durable evidence of acknowledged migration execution, distinct from acceptance of an observed
structural result or proof of application readiness.

**Structural Reconciliation**:
Explicit acceptance of a proved schema outcome after uncertain execution, without asserting
that unacknowledged data work ran.

**Adoption**:
An explicit initial claim of migration ownership over matching existing schema facts, not a
claim that an earlier migration chain executed.

**Preservation**:
Retention of existing unmanaged schema facts and data while owned facts change, without
acquiring ownership of the retained facts.

**Relinquishment**:
An explicit end to migration ownership without deleting the corresponding schema or data.
_Avoid_: Deletion, drop

**Application Readiness**:
Compatibility of the application with its actual schema, data, codecs and operating conditions,
which neither migration completion nor a partial structural check alone establishes.
_Avoid_: Schema equality
