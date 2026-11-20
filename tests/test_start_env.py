import os

from start import load_env_file


def test_load_env_file_parses_without_third_party_deps(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text('# comment\nDASHBOARD_PORT=8555\nQUOTED="value"\n')

    monkeypatch.delenv("DASHBOARD_PORT", raising=False)
    monkeypatch.delenv("QUOTED", raising=False)
    load_env_file(env_file)

    assert os.environ["DASHBOARD_PORT"] == "8555"
    assert os.environ["QUOTED"] == "value"
