# Security policy

## Supported versions

Security fixes are made on the latest stable minor of the latest stable major.
A new stable minor or major ends support for older lines; prereleases do not.
There is no overlapping backport window or LTS promise. Reports affecting older
versions are welcome, but a fix may require upgrading. The
[compatibility policy](docs/compatibility.md#security-and-backports) explains the
support window and its distinction from API deprecation periods.

Python 3.14+, maintained MariaDB LTS targets from 10.11, and SQLite through Python's standard
library are the supported runtime baseline; MySQL is not supported.

## Reporting a vulnerability

Use GitHub's **Security → Report a vulnerability** form to submit a private
report. Do not open a public issue for a suspected vulnerability.

Include the affected snekql version, backend, database version, reproduction,
and expected impact. We aim to acknowledge reports within seven days, on a
best-effort basis. There is no guaranteed response or fix deadline. Please allow time for investigation and a coordinated fix before disclosure.
