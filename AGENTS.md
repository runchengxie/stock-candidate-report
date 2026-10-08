# Stock candidate report development
Read ../quant-workspace-standards/AGENTS.md or its CODE_ROOT equivalent.
Keep watchlists, credentials, provider responses, caches and generated reports outside source control.
Use Python 3.12+, uv, isolated task branches and worktrees.
Validate: uv sync --locked; uv run ruff check .; uv run pytest -q.
Never replace missing data with zero or relabel next-fiscal-year PE as NTM.
Tests use synthetic responses; live checks run only against explicitly configured free sources.
