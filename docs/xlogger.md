# xlogger (datamagix.xlogger)

A lightweight logging helper built on top of `structlog` with ANSI-coloured console output via `colorama`, JSON file sinks, and simple indentation helpers.

**What it provides**

- Colourised human console output (via a custom `_ColourRenderer`).
- Plain non-ANSI renderer for file sinks (`_PlainRenderer`) and a mirroring processor so file sinks receive copy of events.
- Simple global API via the `Logger` class: `Logger.configure(...)`, `Logger.get(name)`, `Logger.add_file_sink(...)`, `Logger.indent()` / `Logger.push()` / `Logger.pop()`.
- Optionally emit JSON lines for structured logs.

**Dependencies**

- `structlog` (>=25)
- `colorama` (recommended; used for Windows terminal colours)

Install via pip:

```bash
pip install structlog colorama
```

Or add to `pyproject.toml` / `requirements.txt` as appropriate. Example (`pyproject.toml` / Poetry):

```toml
[tool.poetry.dependencies]
python = "^3.10"
structlog = "^25.4.0"
colorama = "^0.4.6"
```

**Copying into another repo**

1. Copy `xlogger.py` into your project's package (for example `myproj/logging/xlogger.py`) or add it as a small utility module.
2. Ensure `structlog` and `colorama` are added to your project's dependencies.
3. Import and configure early in your application's startup (before other modules that log):

```python
from logging import getLogger
from myproj.logging.xlogger import Logger

# Configure once at startup
Logger.configure(level="INFO", json=False)
# Optionally add a rotating file sink for errors
Logger.add_file_sink("logs/errors.log", level="ERROR", rotate=True)

# Then get a bound logger for modules
log = Logger.get(__name__)
log.info("started", foo="bar")
```

If you place `xlogger.py` at top-level (not inside a package), import with `from xlogger import Logger`.

**API reference (summary)**

- `Logger.configure(*, level: str|int|None = None, json: bool = False, enabled: bool = True)`
  - One-time global configuration. `json=True` emits JSONRenderer for console.
- `Logger.get(name: str | None = None)` → `structlog.BoundLogger`
  - Returns a bound logger; if `name` provided it's bound as `module` (and used for module colouring).
- `Logger.add_file_sink(path: str, *, level: str|int = "ERROR", rotate: bool = True, use_json: bool = False, ...)` → `logging.Handler`
  - Mirrors events at-or-above `level` into the file. `use_json=True` writes JSON lines; otherwise uses a plain renderer.
- `Logger.remove_file_sink(handler)`
- Indentation helpers: `Logger.indent()`, `Logger.push(steps=1)`, `Logger.pop(steps=1)`, `Logger.set_indent_unit(unit)`
  - Indentation is stored in a `contextvars.ContextVar`, so it is task-local (works well with async code).
- `Logger.set_level(name, level)`, `Logger.disable()`, `Logger.enable(level=None)`

**Examples**

Console, coloured output (default):

```python
from myproj.logging.xlogger import Logger

Logger.configure(level="DEBUG", json=False)
log = Logger.get("MYMOD")
log.info("Hello world", user="alice")

with Logger.indent():
    log.debug("Inside block")
```

JSON output (console or file sinks):

```python
Logger.configure(level="INFO", json=True)
log = Logger.get(__name__)
log.info("structured event", id=123)
```

Add an error file sink (rotating):

```python
handler = Logger.add_file_sink("logs/errors.log", level="ERROR", rotate=True, use_json=False)
# To remove later: Logger.remove_file_sink(handler)
```

**Notes & portability**

- `colorama.init(autoreset=True)` is called in the module to make colours work reliably on Windows.
- The module uses `structlog` processors and `logging.basicConfig(force=True)` during `Logger.configure()` which will replace existing root handlers. Configure once early.
- File sinks are also attached to the root `logging` logger so third-party libraries that emit logging records still get written to the sink.

**Suggested minimal integration checklist for moving to a new repo**

- [ ] Copy `xlogger.py` to your package (`myproj/logging/xlogger.py`).
- [ ] Add `structlog` and `colorama` to dependencies.
- [ ] In your app entrypoint, call `Logger.configure(...)` before importing modules that log.
- [ ] Optionally call `Logger.add_file_sink(...)` to persist ERROR+ messages.
- [ ] Replace direct `logging.getLogger(...)` uses with `Logger.get(...)` where you want the new format/colours.

---

If you want, I can:

- Add a short runnable example script in `examples/` that demonstrates console colours and file sink writes.
- Update `pyproject.toml` in this repo with a minimal `[tool.poetry.group.dev]` / `requirements.txt` excerpt for the extracted module.

Which of those should I add next?