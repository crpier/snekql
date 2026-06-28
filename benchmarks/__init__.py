"""Standalone concurrency/throughput benchmarks for snekql (GitHub issue #66).

These are deliberately separate from the ``snektest`` unit suite: they spin up
real databases, drive concurrent async load, and report timing distributions.
They are run on demand, not as part of CI. See ``benchmarks/README.md``.
"""
