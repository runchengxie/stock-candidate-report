"""Keep generated test artifacts under the explicitly configured data root."""

from uuid import uuid4

from stock_candidate_report.config import load_roots


def pytest_configure(config):
    if config.option.basetemp:
        return
    try:
        roots = load_roots(None, {})
    except (ValueError, OSError):
        return  # CI without personal workspace settings uses pytest's native temp root.
    parent = roots.project_data / "test-tmp"
    parent.mkdir(parents=True, exist_ok=True)
    # Pytest may remove its base directory. Use a new task-owned child, never a data root.
    config.option.basetemp = str(parent / ("pytest-" + uuid4().hex))
