# Non-functional requirements

## Performance
- No specific requirements for Phase 1.

## Security
- **Secrets**: Passwords, connection strings, API keys, and other secrets must not be written to logs (stdout, stderr, or any log file).

## Dependencies
- **Phase 1**: Support the **latest LTS (long-term support) versions** of SQLAlchemy and SQLModel. Exact version bounds are defined in the package metadata (e.g. pyproject.toml); this requirement ensures compatibility with current stable usage.

## Documentation
- **Public API**: The public API must be documented for consumers (e.g. README and API reference, such as Sphinx-generated docs).

## Deployment
- **Platform**: Linux only for Phase 1. Other platforms may be best-effort or added later.
- **Distribution**: Package is published to PyPI and installable via `pip install dbconform` (or the package name as published).

## Observability

### Auditability and logging
- **Minimum**: All applied changes (and relevant dry-run outcomes) are emitted as **structured** logs to **stdout** so that runs can be audited and consumed by log aggregators or CI. The format must be **machine-parseable** (e.g. JSON lines) to support tooling and CI.
- **Optional**: An option must exist to **also** write the same (or a human-readable) log to a **text file**, for local audit trails or archival.

## Acceptance criteria (non-functional)
- Logs are structured and machine-parseable; no secrets appear in logs. Package is installable on Linux via pip (PyPI). Public API is documented (e.g. README and API reference).
