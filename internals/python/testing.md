# Python testing conventions

## Framework

- **pytest** with **pytest-describe** — group tests in `describe_*` blocks and
  name cases `it_*` (collected via `python_functions = ["test_* describe_*"]`).
  Plain `test_*` functions are still collected.
- **`asyncio_mode = auto`** (pytest-asyncio) — async tests need no per-test
  marker.

## File layout

- Classic `test_*.py` and colocated `*_test.py` are both collected
  (`python_files = ["test_*.py", "*_test.py"]`). Prefer colocated `*_test.py`
  for fast unit tests near the code they cover.
- `tests/` holds integration tests that start real devcontainers (slow; many
  skip without Docker). They carry the `integration` / `claude` markers.
- Shared fixtures live in `tests/conftest.py`.

## Mocking

The suite mocks with `unittest.mock` (the `pytest-mock` `mocker` fixture is not
in the dev set). Follow that pattern — see `tests/test_isolation_test.py`.

## Coverage

Coverage runs via **pytest-cov** over `src/lamp_the_djinn` with branch
coverage; `src/lamp_the_djinn/devcontainer/*` (shipped shell/Dockerfile/json
data) is omitted. There is no enforced `fail_under` yet: most tests need Docker
and are skipped in unit CI, so a hard gate would falsely fail. `fail_under = 85`
is left commented in `pyproject.toml` as an aspirational target — enable it once
unit coverage is representative.

## Running

```bash
uv run pytest                 # full suite
uv run pytest tests/test_cli.py
uv run pytest --cov           # with coverage
```
