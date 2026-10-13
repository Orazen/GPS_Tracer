"""Tachograph import and driving-time reporting for GPS_Tracer.

Scope, stated up front because it is easy to overclaim:

* This package **parses** tachograph download files (.DDD) and **normalises**
  the activity records they contain into application tables.
* It **calculates** EU driving-time obligations from those records, but the
  output is explicitly **not** a legal finding. Every calculation carries the
  rules version and the source coverage it was made from, and degrades to
  ``unknown`` rather than guessing.
* It does **not** talk to a tachograph directly. Live/remote download is a
  separate, deliberately unimplemented concern — see docs/LIVE-TACHO.md.

The parser, the activity model and the rules engine import nothing outside the
standard library. Only the HTTP layer and the database layer have dependencies.
"""

__version__ = "0.1.0"

# Bumped whenever parsing behaviour changes in a way that could alter the
# normalised activity output for the same input file. Stored on every import so
# a re-parse can be tell whether old rows are stale.
PARSER_VERSION = "gen1-0.1.0"
