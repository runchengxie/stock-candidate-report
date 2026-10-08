import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Roots:
    code_root: Path
    data_root: Path
    config_root: Path

    @property
    def project_data(self):
        return self.data_root / "stock-candidate-report"

    @property
    def project_config(self):
        return self.config_root / "projects" / "stock-candidate-report"


def load_roots(settings_path: Path | None, overrides: dict[str, str]) -> Roots:
    path = settings_path or Path(
        os.environ.get(
            "STOCK_REPORT_WORKSPACE_CONFIG",
            str(Path.home() / ".config/runchengxie/shared/workspace.toml"),
        )
    )
    data = tomllib.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    for key in ("code_root", "data_root", "config_root"):
        value = overrides.get(key) or os.environ.get(key.upper())
        if value:
            data[key] = value
    if any(not data.get(key) for key in ("code_root", "data_root", "config_root")):
        raise ValueError(f"Set --workspace-config to a workspace.toml with all three roots: {path}")
    return Roots(
        **{
            key: Path(data[key]).expanduser().resolve()
            for key in ("code_root", "data_root", "config_root")
        }
    )


def project_settings(roots: Roots) -> dict:
    path = roots.project_config / "settings.toml"
    return tomllib.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
