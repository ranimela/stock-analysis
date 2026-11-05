# Lessons Log
Add one line per problem that cost time (what happened, what rule or convention would have prevented it).
Promote repeated lessons into `conventions.md` here and into the master template.

- (date) (what went wrong) -> (fix)
- 2026-11-05 Running `ruff check --fix` on local Python 3.14 before setting `target-version = "py310"` in `ruff.toml` rewrote `timezone.utc` to `datetime.UTC` (Python 3.11+ only), breaking the Python 3.10 GitHub Actions workflow -> Always set `target-version = "py310"` in `ruff.toml` before running `ruff --fix`, or match CI Python version to target version.
