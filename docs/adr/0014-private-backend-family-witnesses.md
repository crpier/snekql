# Private backend-family witnesses enforce namespace isolation

SQLite and MariaDB models, queries, configurations, and Transactions carry a private `Literal["sqlite"]` or `Literal["mariadb"]` witness through static interfaces. Backend Namespace aliases pin and hide that witness, preserving application annotation arity for `Model`, `Select`, `Write`, and `Transaction`; runtime guards remain for casts, `Any`, and dynamic declarations.

Backend-specific facade classes were rejected because they duplicated every query and runtime overload while detecting mixed joins only at Transaction consumption. `ty` also rejects dependent generic bounds tying a model owner indirectly to a family variable, so accepted protocols and private query carriers expose the family coordinate directly.
