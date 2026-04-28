# AGENTS.md

## Project Context

This repository is a Python project using Python 3.11, as defined in `.python-version`.

The repository is newly initialized and currently has no committed source tree, package metadata, or test configuration. Treat the project structure as still forming, and avoid assuming a framework until the relevant files are added.

## Working Guidelines

- Keep changes small and focused.
- Prefer adding project conventions only when the codebase needs them.
- Do not commit generated caches, virtual environments, local secrets, or editor files.
- Preserve user changes already present in the working tree.
- Use clear commit messages once changes are ready to be committed.

## Python Conventions

- Target Python 3.11 compatibility unless the project configuration changes.
- Prefer standard library solutions before adding dependencies.
- If dependencies are added, also add or update the project metadata file that manages them.
- Keep formatting and linting aligned with the tools configured in the repository. If no configuration exists yet, avoid introducing broad formatting churn.
- Use type hints for new public functions and interfaces.

## Validation

Before handing work back, run the most specific available checks. As the repository grows, prefer:

- Unit tests for changed behavior.
- Ruff or the configured linter for style issues.
- Mypy or the configured type checker for typed modules.

If no validation command exists yet, state that clearly in the handoff and explain any manual checks performed.

## Git Notes

- The repository is connected to Git, but it currently has no commits.
- Check `git status --short --branch` before and after edits.
- Do not run destructive Git commands such as `git reset --hard` or `git checkout -- <path>` unless explicitly requested.
- Keep unrelated working tree changes intact.

## Files To Avoid

The following are generated or local-only and should not be committed:

- `.mypy_cache/`
- `.ruff_cache/`
- `.pytest_cache/`
- `.ty/`
- `.venv/`
- `__pycache__/`
- `.env` and other local environment files
