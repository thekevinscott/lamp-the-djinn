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

## Dockerfile parity

`tests/integration/dockerfile_parity_test.py` pins the shared invariants
between the two cage Dockerfiles (`.devcontainer/Dockerfile`, published by CI,
and `src/lamp_the_djinn/devcontainer/Dockerfile`, the packaged local-build
fallback): base image version, pinned tool versions, the apt/pnpm/Claude
Code/pi install steps, the firewall-script `COPY`s, and the `ENV` block. It
does **not** assert byte equality -- the two files legitimately differ (Docker
CLI, the pinned global Playwright CLI, and OCI labels are specific to one
image or the other; see the comments in each file). Uses `dockerfile-parse` to
read real Dockerfile instructions rather than diffing raw lines, so it isn't
thrown off by comments or by content that's deliberately only on one side.

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
