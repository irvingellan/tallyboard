# Contributing to Tallyboard

Thanks for looking. This project is small on purpose and very open to help:
bug reports, "it works on my tablet" notes, translations and code are all
welcome.

## Ways to help

**Report a device.** Tallyboard has been tested on exactly one tablet, a 2017
Amazon Fire HD 10. If you try another one, open an issue with the device, its
OS and browser, and what you saw. A photo helps. "It works" reports are as
useful as bug reports.

**Add a language.** Every word on screen is in the `LANG` table at the top of
`tallyboard/static/console.js`. Copy the `en` block, translate it, add the
language code to `LANGUAGES` in `tallyboard/server.py` and to the `--lang`
choices in `install.py`, and add a line to the language test in
`tests/console.test.mjs`.

**Add an agent.** The board shows whatever writes a JSON file into
`~/.local/state/tallyboard/agents.d/`. The fields are listed in
`from_dropin()` in `tallyboard/state.py`; `tallyboard/hooks/claude_code_hook.py`
is a complete example. For agents that keep their own index on disk, see
`tallyboard/codex.py` for a read-only reader.

**Fix or improve something.** Open an issue first for anything larger than a
small fix, so we can agree on the direction before you spend time on it.

## Ground rules

- **The page must keep working on very old browsers.** It is plain ES5 and CSS
  without variables, grid, `gap` or `clamp`. A test fails if modern syntax
  slips in. This is the whole point of the project, so please do not "modernise" it.
- **No dependencies.** The server and hook use only the Python standard library.
- **Nothing leaves the local network**, and the board never reads code, command
  lines or the agent's replies. Changes that weaken either will not be merged.
- **Sample data only in screenshots and tests.** Use `?demo=...`; never commit
  captures of real sessions.

## Running the tests

```bash
python3 tests/test_console.py
python3 tests/test_install.py
python3 tests/test_safety.py
node --test tests/*.mjs
```

The installer tests run inside a temporary folder and never touch your real
Claude Code settings.

## Trying a change

```bash
python3 tallyboard/server.py --port 5298 --state-dir /tmp/tallyboard-dev --allow-demo
```

Then open `http://localhost:5298/?demo=cycle`. Narrow the browser window to a
tablet shape to see it as the tablet does.
