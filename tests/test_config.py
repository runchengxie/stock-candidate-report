from pathlib import Path

import pytest

from stock_candidate_report.config import load_roots


def test_roots_and_overrides(tmp_path):
    p = tmp_path / "workspace.toml"
    p.write_text('code_root="/code"\ndata_root="/data"\nconfig_root="/config"')
    roots = load_roots(p, {"data_root": str(tmp_path / "private-data")})
    assert roots.data_root == tmp_path / "private-data"
    assert roots.project_config == Path("/config").resolve() / "projects/stock-candidate-report"


def test_missing_config_is_actionable(tmp_path):
    with pytest.raises(ValueError, match="workspace"):
        load_roots(tmp_path / "absent.toml", {})
