# Working in lamp-the-djinn

Produce as little code as possible. Drive existing tools through their own
flags and config before writing an adapter. Every line is a liability.

## Red test first, always

**Every implementation starts with a test going red, FIRST.** Before you touch
the implementation, write the test that fails because the behavior is missing or
broken, and *witness it red*. Only once you have seen red do you implement, and
you are done when that same test goes green — not before.

This is not ceremony. The EROFS regression that motivated this rule shipped
"fixed and verified" while the deployed `ltd` was still broken: the test was
green for the wrong reason (it exercised the source tree, not the artifact the
user runs). A test you have not watched fail is a test you cannot trust.

For a behavior change, the order is:

1. Write the **e2e** test (and, where the decision is pure, the **integration**
   test) that pins the new behavior. Run the e2e locally; watch it go red.
2. Write or update the **docs** alongside the red test (see *Docs first*).
3. Implement until the test goes green. Leave every other test green.

Reach for a workflow first when the change is structural and you suspect the
red comes from more than one place; otherwise a single red test is enough.

## The three test tiers

The boundary is structural — by location, not by how careful you are.

- **Unit** — colocated with source: `src/lamp_the_djinn/foo.py` →
  `src/lamp_the_djinn/foo_test.py`. Pure logic, every collaborator mocked, no
  Docker, no subprocess, no network. Fast. Marker `unit`.
- **Integration** — `tests/integration/`, files end `_test.py`. First-party code
  (e.g. `modify_config`) runs *for real*; the real, controlled collaborator here
  is the host filesystem and process env. No container is spun up. Marker
  `integration`.
- **E2E** — `tests/e2e/`, files end `_test.py`. A real cage via the **deployed**
  `ltd` CLI. Slow, needs Docker, not run in CI. Marker `e2e` (plus `claude` for
  cells needing a real model turn).

Select a tier with `-m unit` / `-m integration` / `-m e2e`. Style is
pytest-describe: `describe_*` blocks, `it_*` functions.

## Two lessons the EROFS bug taught, encoded here

**Exercise the deployed artifact, never the source.** An e2e test must invoke
the installed `ltd` console script — the thing the user runs — not
`uv run lamp-the-djinn` against `src/`. Under `uv run`, the editable install
shadows the deployed binary and the test silently validates the fix-in-source
while the shipped binary stays broken. `tests/e2e/coding_agent_test.py` resolves
the real binary and *prints which artifact it ran*; honor that pattern. CI
installs the package from the PR source before e2e.

**Own the precondition.** The EROFS only fired when the host harness-cache was
warmed *and* the target package absent — a state-dependent bug. A test that
relies on ambient state (the developer's real `~/.cache`) is non-deterministic
and will go green by accident. Construct the exact triggering state under an
isolated, monkeypatched `HOME`, so the test is red on broken code every time.

## Docs first

Every behavior change updates docs *alongside the red test*, before the
implementation. User-visible change → `README.md` / `ARCHITECTURE.md`. Internal
change → `internals/`. A docs-only change (Markdown only, no behavior) skips the
red/green dance: every existing test stays green, so go straight to it.

## Now over later

Make the complete, correct change in this PR. Don't punt to a hypothetical
follow-up, leave a TODO where the real change belongs, or keep a
backwards-compatible shim to avoid touching a caller. "Now" means the needed
change, not speculative future-proofing.

## Enforcement

`testing-conventions` runs these rules deterministically in CI, via
`.github/workflows/conventions.yml`: colocated unit tests, unit-test isolation,
one non-trivial function per module (`unit one-function-per-file`, scanning
`src`), integration tests that don't mock first-party code, the unit-coverage
floor, mutation testing on the lines a PR changed (`unit mutation`, scanning
`src`), packaging hygiene (no test files in the built wheel/sdist), and e2e
attestation freshness. It is the gate; this document is the why. See
`testing-conventions.toml` for the project's floors and exemptions.

`unit mutation` is the rung above the coverage floor. Coverage asks whether a
line ran; mutation asks whether any test would notice if that line were wrong.
That is why the floor can stay loose at 50% — the floor is a ratchet, and
mutation is what actually holds the unit suite honest. The gate is binary, not a
score: no unexplained surviving mutant on a line the PR touched. It runs on pull
requests only and mutates only the files in `<base>...HEAD`, because a whole-tree
sweep is too slow to gate on.

A survivor means one of two things, and they need different fixes. If the unit
suite should have caught it, add the assertion. If the line is genuinely asserted
at another tier — the integration suite runs first-party code for real, so
host-env branches live there — it gets an exemption in `testing-conventions.toml`
naming the exact lines and the test that does assert on them. Whole-file
mutation exemptions are rejected by the tool, and a listed line that isn't
actually failing is a hard error, so the waiver list can't rot. Don't add one
pre-emptively; add it in the PR that trips it.

An interrupted mutation run leaves the live mutant written into the source file.
Check the working tree is clean before you trust a local result.

`one-function-per-file` is why `src/lamp_the_djinn/` is many small modules
rather than one `cli.py`: a source file may hold at most one module-scope
function whose body runs longer than a line. Trivial one-liners still share a
file. A new non-trivial function means a new module — and, via
`colocated-test`, a new sibling `*_test.py`.

CI calls the upstream **reusable workflow**
(`thekevinscott/testing-conventions/.github/workflows/testing-conventions.yml@v0`),
which runs each rule as its own job. Don't re-hand-roll these as `npx` steps:
the previous hand-rolled version drifted, silently missing
`one-function-per-file` and `mutation` entirely. A new upstream rule arrives
with a release instead of waiting for someone to notice it is absent.

The binary is **not** a project dependency — it's a standalone CLI. Locally, run
it through npm (`pnpm dlx testing-conventions@<version>`): the npm and PyPI
release trains differ, and the versions the workflow pins exist on npm only.
Every rule takes the package root, `src` — including `integration lint`, which
derives `tests/integration` itself and does **not** flag the colocated unit
tests' legitimate `monkeypatch`/`patch` use. `unit coverage` shells out to
`coverage`/`pytest`, so run it with the project venv on PATH. For example:

```sh
pnpm dlx testing-conventions@0.0.120 integration lint --language python --config testing-conventions.toml src
```

`unit mutation` needs one more thing: its Python engine is a *separate PyPI
package* that happens to share the name, and it must be importable by the
`python3` the rule shells out to. Layer it over the project venv rather than
locking it in — it isn't a project dependency either:

```sh
uv run --with testing-conventions pnpm dlx testing-conventions@0.0.120 \
  unit mutation --language python --base origin/main \
  --config testing-conventions.toml src
```

E2E is never run in CI (real containers and model turns are slow and cost
money). Run it locally and attest:

```sh
uvx testing-conventions e2e attest 'uv run pytest -m e2e'
```

Commit the resulting receipt — current versions write a per-branch
`e2e-attestations/<branch>.json` rather than the legacy root
`e2e-attestation.json`, and both are tracked here. CI's `e2e verify` checks it
names the current commit.
