# SELECT readiness without acknowledgment

SELECT is executable from construction because explicit filtered/unfiltered acknowledgment hindered composition without establishing useful cardinality guarantees. Fetch methods retain consumption contracts after SQL filtering and pagination; UPDATE and DELETE retain explicit scope guards. SELECT `.all()` remains an identity operation for compatibility, including around filters; locking reads also need no acknowledgment, while dialect and transaction checks remain authoritative.

Putting one/many contracts on query objects was rejected because it would add query types and composition rules without resolving the redundant read acknowledgment. The private SELECT readiness coordinate remains to avoid unrelated annotation churn; factories now produce executable reads, while scope, backend, and compilation checks still apply.
