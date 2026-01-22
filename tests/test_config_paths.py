from pathlib import Path

from moex_carry.config import AppSettings, DataConfig, _repo_root, resolve_paths


def test_resolve_paths_anchors_relative_data_dir():
    settings = AppSettings(data=DataConfig(data_dir="data"))
    paths = resolve_paths(settings)
    assert paths.data_dir == _repo_root() / "data"


def test_resolve_paths_keeps_absolute_data_dir(tmp_path: Path):
    settings = AppSettings(data=DataConfig(data_dir=str(tmp_path)))
    paths = resolve_paths(settings)
    assert paths.data_dir == tmp_path
