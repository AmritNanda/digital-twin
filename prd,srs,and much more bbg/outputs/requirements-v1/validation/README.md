# Reproducing specification checks

Run `python validation/validate_specification.py` from this package directory using Python with `jsonschema` available. The script validates document IDs/links, strict core-schema examples and rejection cases, fictional accounting arithmetic, and the acyclic implementation dependency graph. It writes `SPECIFICATION_VALIDATION.md`.

This is documentation validation, not product implementation or product acceptance testing. It does not make network calls. Date-time format checking is explicitly registered because optional JSON Schema format dependencies may not be installed.

Authoring environment: Python 3.13.11, jsonschema 4.26.0.
