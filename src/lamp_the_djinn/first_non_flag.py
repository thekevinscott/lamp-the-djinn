"""Scan an argv tail for its package spec."""

from collections.abc import Container

# Options of npx / npm exec and uvx / uv tool that consume the next token. Their
# values must never be mistaken for the package spec: the manifest is installed
# on the host by scripts/refresh-harness-cache.sh.
TAKES_VALUE = frozenset(
    "-p --package --from -c --call -w --workspace --with --with-editable"
    " --with-requirements --constraints -b --build-constraints --overrides"
    " --env-file --python --python-platform --torch-backend --index"
    " --default-index -i --index-url --extra-index-url -f --find-links"
    " --index-strategy --keyring-provider --resolution --prerelease"
    " --exclude-newer --link-mode --cache-dir --color --allow-insecure-host"
    " --directory --project --config-file --registry --cache --userconfig"
    " --globalconfig --prefix -C --loglevel --tag --scope --before --omit"
    " --include --allow-scripts".split()
)


def first_non_flag(args: list[str], package_opts: Container[str] = ()) -> str | None:
    """Return the package spec: a `package_opts` value, else the first positional."""
    tokens = iter(args)
    for a in tokens:
        name, eq, value = a.partition("=")
        if name in package_opts:
            return value if eq else next(tokens, None)
        if a in TAKES_VALUE:
            next(tokens, None)
        elif not a.startswith("-"):
            return a
    return None
