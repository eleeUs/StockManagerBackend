# Running Tests from VS Code

Two ways to do this. Use **Option A** if you just want to click "run" on
tests and see results in the Testing sidebar with breakpoints working.
Use **Option B** if you'd rather not install anything locally and are
fine running everything through Docker from the integrated terminal.

Files already set up in this repo for Option A:
`.vscode/settings.json`, `.vscode/launch.json`, `.env.test.local.example`.

---

## Option A — Native VS Code Testing sidebar (recommended)

Gives you: the Testing sidebar (flask icon) with a green/red status per
test, click-to-run individual tests, and breakpoints that actually stop
execution.

### 1. Start Postgres

You still need the database running — just not necessarily the `api`
container, since VS Code will run pytest directly on your machine.

```bash
docker-compose up -d db
```

### 2. Create a local virtualenv

```bash
python3.12 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements/development.txt
```

### 3. Create your local env file

```bash
cp .env.test.local.example .env.test.local
```

The defaults in that file already point `DATABASE_URL` at
`localhost:5432` instead of the Docker service name `db` — that's the
one thing that has to differ from the `.env` used by `docker-compose`.
No further edits needed unless your local Postgres port differs.

### 4. Point VS Code at the venv

`Ctrl/Cmd+Shift+P` → **Python: Select Interpreter** → pick
`./.venv/bin/python`. If you don't see it listed, reload the window
(`Ctrl/Cmd+Shift+P` → **Developer: Reload Window**) — `.vscode/settings.json`
already sets `python.defaultInterpreterPath` for you, this step is just
confirming VS Code picked it up.

### 5. Open the Testing sidebar

Click the flask/beaker icon in the left activity bar. VS Code discovers
tests using `pytest.ini`'s rules (`test_*.py`, classes starting with
`Test`, functions starting with `test_`) — the exact same discovery the
CI job and `make test` use, so what passes here passes there.

First run can take a few seconds while pytest collects everything. After
that:

- Click the ▶ next to any test, class, or file to run just that.
- Click the 🐛 (debug) icon next to a test to run it with breakpoints
  active — set a breakpoint by clicking left of a line number first.
- Run everything with the ▶ at the top of the sidebar, or `Ctrl/Cmd+;` `A`.

### 6. Sanity check for Phase 8 Part 1 specifically

Filter the Testing sidebar to `apps/idempotency`, or run from the
integrated terminal:

```bash
pytest apps/idempotency -v
```

If this passes, Part 1 is confirmed working in isolation before Part 2
wires it into any real endpoint. Then confirm nothing else broke:

```bash
pytest --tb=short -q
```

Three ready-made debug configurations are also in `.vscode/launch.json`
(**Run and Debug** panel → dropdown at the top): "Pytest: current file",
"Pytest: apps/idempotency (Phase 8 Part 1)", and "Pytest: full suite" —
same effect as the Testing sidebar, useful if you want a persistent
launch shortcut instead of clicking through the sidebar each time.

---

## Option B — Through Docker, from the integrated terminal

No local Python setup at all — just open VS Code's terminal
(`` Ctrl/Cmd+` ``) and run the same commands you'd run from any terminal:

```bash
make up          # or: docker-compose up -d
make migrate

# Everything
make test

# Just Phase 8 Part 1
docker-compose exec api pytest apps/idempotency -v

# A single test
docker-compose exec api pytest apps/idempotency/tests/test_services.py::TestRollbackSemantics -v
```

You lose the Testing sidebar and one-click breakpoint debugging this
way — output is plain terminal text, same as running it outside VS Code
entirely. If you later want breakpoints without leaving Docker, the
**Dev Containers** extension (`ms-vscode-remote.remote-containers`) lets
VS Code attach directly inside the `api` container so Option A's
workflow works there too — not set up in this repo yet, but worth
adding if Docker-parity testing becomes a recurring need.

---

## Troubleshooting

- **Testing sidebar shows "0 tests found"** — usually the interpreter.
  Confirm the status bar (bottom left) shows `.venv` as the active
  interpreter, not a system Python.
- **`django.db.utils.OperationalError: could not connect to server`** —
  Postgres isn't reachable at `localhost:5432`. Confirm
  `docker-compose up -d db` is actually running (`docker ps`) and that
  nothing else on your machine is already bound to port 5432.
- **Tests pass in the terminal but the sidebar still shows red** — reload
  the window; the Python extension sometimes caches a stale discovery
  run after a config change.
