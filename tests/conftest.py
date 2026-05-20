import pytest


@pytest.fixture
def make_input_file(tmp_path):
    """Factory fixture: write lines to a temp file and return its path."""
    def _make(lines: list[str]) -> str:
        p = tmp_path / "input.txt"
        p.write_text("\n".join(lines), encoding="utf-8")
        return str(p)
    return _make


@pytest.fixture
def output_file(tmp_path) -> str:
    return str(tmp_path / "output.jsonl")
