# Stock candidate report development
Read ../quant-workspace-standards/AGENTS.md or its CODE_ROOT equivalent.
Keep watchlists, credentials, provider responses, caches and generated reports outside source control.
Use Python 3.12+, uv, isolated task branches and worktrees.
Validate: uv sync --locked; uv run ruff check .; uv run pytest -q.
Also validate Excel: uv sync --locked --extra excel; uv run --extra excel pytest -q.
JSON is the default output. Excel uses optional openpyxl; no Node or private runtime is required.
Tests disable network sockets. Do not weaken this to make live-provider tests pass in CI.
Never replace missing data with zero or relabel next-fiscal-year PE as NTM.
Tests use synthetic responses; live checks run only against explicitly configured free sources.
