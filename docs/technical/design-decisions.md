# Design Decisions

This document records significant design decisions made during the development of dbconform, including the rationale and context for each choice. These decisions serve as reference for maintainers and AI agents working on the project.

---

## DD-001: Error Handling Strategy for `compare()` vs `apply_changes()`

**Date**: 2026-06-11  
**Status**: Accepted  
**Context**: Issue #12 implementation surfaced questions about when to raise exceptions vs return error objects.

### Decision

dbconform uses different error-handling semantics for analysis vs execution operations:

1. **`compare()` (analysis/dry-run)**: Always returns `ConformPlan | ConformError`
   - Never raises exceptions for schema drift or blocking conditions
   - Drift detection and analysis IS the purpose of this method
   - Users inspect the result to understand what changes would be needed

2. **`apply_changes()` (execution)**: Raises exceptions by default when conformity fails
   - New parameter: `raise_on_error: bool = True`
   - When `True` (default): Raises `ConformError` if error-severity skipped steps prevent conformity
   - When `False`: Returns `ConformError` for programmatic inspection (advanced use cases)
   - The command semantics are "make the database conform" - failure to do so is exceptional

### Rationale

The killer feature of dbconform is not detecting drift (which is relatively simple) but **automatically fixing it**. When a user calls `apply_changes()`, they are commanding the tool to make their database match their models. If this operation fails, it violates the user's expectation and should interrupt program flow by default.

#### Contract Differences

- **`compare(models)`**: "What would need to change?" → Analysis result (plan or error)
- **`apply_changes(models)`**: "Make it conform" → Success (plan) or failure (exception)

This mirrors established patterns in infrastructure tooling:
- `terraform plan` (returns analysis) vs `terraform apply` (exits non-zero on failure)
- `git diff` (shows differences) vs `git apply` (fails with error)
- `kubectl diff` (shows changes) vs `kubectl apply` (raises on error)

#### Why Not Always Raise?

The opt-out flag (`raise_on_error=False`) supports advanced use cases:
- CI/CD pipelines that want to log all blocking issues without aborting
- Scripts that need to inspect `ConformError.plan` to make programmatic decisions
- Test fixtures that validate error conditions

But these are edge cases. The default behavior (raising) provides the least-surprising semantics for the common case: "I told you to conform, so if you didn't, stop and tell me why."

#### Why `ConformError` Still Inherits from `Exception`

Even when returned (not raised), `ConformError` is an `Exception` subclass. This provides:
1. Users can explicitly `raise result` if they want strict exception handling
2. The exception's `__str__` provides formatted error messages
3. The `plan` attribute gives structured access to what would have been applied
4. Flexibility without forcing users into a single error-handling style

### Implementation

```python
# compare() - always returns, never raises
plan = conform.compare(models)
if isinstance(plan, ConformError):
    # Blocking conditions found; inspect plan.plan for details
    handle_drift(plan)

# apply_changes() - raises by default
try:
    plan = conform.apply_changes(models)
    # Success: DDL applied, database conforms
except ConformError as e:
    # Conformity failed: inspect e.plan for details
    log.error(e.messages)
    handle_blocking_issues(e.plan.skipped_steps)

# apply_changes() - opt-out for advanced cases
result = conform.apply_changes(models, raise_on_error=False)
if isinstance(result, ConformError):
    # Programmatic inspection without exceptions
    analyze_and_decide(result.plan)
```

### Consequences

**Positive**:
- Default behavior matches user intuition: execution failures interrupt flow
- Advanced users retain full control via `raise_on_error=False`
- Pattern consistent with infrastructure tooling conventions
- `ConformError.plan` provides rich context in both exception and return scenarios

**Negative**:
- Breaking change for existing code calling `apply_changes()` and checking `isinstance(result, ConformError)`
- Migration path required: users must either add `try/except` or set `raise_on_error=False`
- More complex to explain than "always returns" or "always raises"

**Mitigation**:
- Clear documentation with examples of both patterns
- Prominent mention in CHANGELOG and migration guide
- Version bump reflects breaking change

### Alternatives Considered

1. **Always raise for both `compare()` and `apply_changes()`**
   - Rejected: Forces exception handling even for dry-run analysis
   - Users would need to wrap every `compare()` call in try/except to inspect drift

2. **Always return for both methods**
   - Rejected: Makes execution failures easy to ignore accidentally
   - Users must remember to check `isinstance()` or risk silently skipping conformity

3. **Separate methods like `compare()` and `apply_changes_strict()`**
   - Rejected: API proliferation; two methods doing the same thing with different error semantics

### References

- GitHub Issue #12: NOT NULL backfill, skipped steps, error handling
- docs/requirements/01-functional.md: Error handling, skipped steps
- src/dbconform/errors.py: `ConformError` implementation
- src/dbconform/plan/skipped_policy.py: `finalize_plan_drift()` logic

---

## Template for Future Decisions

```markdown
## DD-XXX: [Title]

**Date**: YYYY-MM-DD  
**Status**: [Proposed | Accepted | Deprecated | Superseded by DD-XXX]  
**Context**: Brief description of the problem or question

### Decision
What we decided to do

### Rationale
Why we made this decision

### Consequences
- **Positive**: Benefits
- **Negative**: Drawbacks and trade-offs
- **Mitigation**: How we address the negatives

### Alternatives Considered
What else we looked at and why we rejected it

### References
Links to related docs, issues, code
```
