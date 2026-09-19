# Related-data loading contract

Research #369. Approved boundaries: list_orders(customer_id, cursor, limit),
get_order(order_id), and observe(backend, strategy). No production fixes.

Immutable application views, fully usable after transaction/session closure.
List filters by customer and sorts placed_seq DESC, id DESC. Cursor is the last
returned pair, exclusive. Fetch limit+1 parents to determine whether another page
exists; next_cursor is null on the last page. Supported limits are positive integers.
Empty orders remain present with zero total and no items. Items sort by line ID.
Details return the same order shape or null for an absent ID. This is not an
authorization boundary; customer-scoped detail authorization is outside scope.

Totals use line quantity times historical unit cents, not product current price.
Prices and quantities are valid fixed integers, with no tax or discount rules.
No writes occur while paginating; this study does not promise cross-request snapshots.

Fixed oracle for customer 1: order IDs [102, 101, 103, 104], totals [125, 880, 0, 150].
Orders 102 and 101 share placed_seq 30; 103 has 20 and 104 has 10.
Order 101 has three lines, including two referencing the same product at different
prices. Order 104 has five lines. Customer 2 has only order 201 with total 700.
Products have deliberately different current prices. IDs, prices, and expected
outputs are specification literals, not generated from a comparator's output.

Compare snekql projected parent/customer join plus batched line/product join with
SQLAlchemy select-in collection loading plus joined scalar relations, and joined
collection loading. Add explicitly awaited per-order loading as a diagnostic,
not representative ORM usage. Fresh sessions per operation prevent warm identity
maps from concealing queries. No raw SQL substitutions in application reads.

Count successful application SELECT statements, excluding setup, control probes,
and transaction-control SQL. Record the full SQL evidence and serialization after
closure. Query counts are observations, not a universal lower-is-better score.
Pagination correctness, exact totals, and detached results are separate checks.
Use real owned temporary SQLite files and socket-only MariaDB servers. No external
URL accepted by the runner. No timing benchmark, throughput claim, usability study,
or general comparison of typing soundness.
