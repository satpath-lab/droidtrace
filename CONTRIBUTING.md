# Contributing

Thanks for wanting to help! Here's how to get going.

## Set up

```bash
git clone https://github.com/satpath-lab/droidtrace.git && cd droidtrace
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,disasm,parquet]"
pre-commit install
```

## Before opening a pull request

```bash
make lint      # ruff + mypy
make test      # unit tests
make plugin QEMU_SRC=/path/to/qemu-10.0.3   # if you touched plugin/
```

- Keep pull requests focused, with a short description of what and why.
- Use [Conventional Commits](https://www.conventionalcommits.org/) (`fix: …`, `feat: …`) and
  sign off your commits (`git commit -s`).
- Changing the trace format? Bump `DT_FORMAT_VERSION` in **both**
  `plugin/include/dtrace_format.h` and `src/droidtrace/format.py`, and update
  [docs/trace-format.md](docs/trace-format.md).

## Ground rules

- Never commit malware samples or traces of real malware. Test fixtures must be harmless and
  self-built (like `tests/apk/`).
- Be kind; see [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
