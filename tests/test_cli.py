import json

from stock_candidate_report.cli import main


def test_cli_help(capsys):
    assert main(["--help"]) == 0
    assert "generate" in capsys.readouterr().out


def test_offline_all_missing_outputs_diagnostics_and_exit_2(tmp_path):
    config = tmp_path / "workspace.toml"
    config.write_text(
        f'code_root="{tmp_path.as_posix()}"\n'
        f'data_root="{(tmp_path / "data").as_posix()}"\n'
        f'config_root="{(tmp_path / "config").as_posix()}"'
    )
    watchlist = tmp_path / "watchlist.json"
    watchlist.write_text('[{"symbol":"AAA","name":"Synthetic","group":"AI"}]')
    rc = main(
        [
            "generate",
            "--workspace-config",
            str(config),
            "--watchlist",
            str(watchlist),
            "--year",
            "2026",
            "--offline",
        ]
    )
    assert rc == 2
    outputs = [
        p
        for p in (tmp_path / "data/stock-candidate-report/outputs").glob("*/候选股-*.json")
        if not p.name.endswith((".verification.json", ".errors.json"))
    ]
    assert len(outputs) == 1
    data = json.loads(outputs[0].read_text(encoding="utf-8"))
    assert data["coverage"]["prices_available"] == 0
    assert data["coverage"]["provider_calls"] == 0
