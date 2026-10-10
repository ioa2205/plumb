# Plumb

Plumb finds the places where a web app shows people data that isn't theirs.

It reads the app's source code on your own computer, with a small AI model that
works offline, and points to the exact lines behind every answer. Your code is
never uploaded and never run.

It is a **working prototype for Windows**. It has been shown working on one
practice app and one laptop, and its limits are listed below.

**Website:** https://plumb-security.vercel.app (in English and Uzbek), with the
recorded test step by step and a guide for installing with an AI agent.

## What it does

- Reads a web app written in Python with FastAPI or TypeScript with Next.js, and
  lists every place that loads someone's data and the checks in front of it.
- Compares places that do the same job. If ten places that open an order check
  who is asking and one does not, that one gets a question.
- Asks a small local AI model short questions about that place, searches for a
  reason it might be fine after all, and needs three agreeing judgments.
- Checks every cited line with ordinary code, then saves a report (HTML,
  Markdown, JSON and SARIF). Each answer is Supported, Rejected or Inconclusive.

## What it does not do

- Upload your code, or need the internet after setup.
- Run your app or attack it. It only reads the code.
- Fix the code for you. Suggested fixes are not reliable yet.
- Promise that an app is safe. An empty report means nothing was found in what
  was checked.

## What is not known yet

- How often it is right. It has been shown on one practice app; it has not been
  measured on real projects.
- Whether it runs on your computer. Every recorded review ran on one laptop: an
  Intel Core i5-1135G7 with NVIDIA GeForce MX350 graphics and 8 GB of memory.
  Other 64-bit Windows computers with an Intel or AMD processor and about 2.4 GB
  of free memory can start a review through a second profile, `cpu-8k`, which
  runs the same model on the processor alone. That profile has completed one real
  run, from source, on the same laptop on 10 October 2026, with the same result
  as the recorded test below. Nothing has been tried on a second computer. The
  downloadable package holds the same code, but no review with the AI model has
  been run from it since it was rebuilt.
- How well it finds other kinds of flaw. In development runs it missed an
  unsafe database query and an exposed phone number.

## The recorded test

On 8 October 2026 Plumb reviewed two addresses of Tandir, the practice
bakery-ordering app in `labs/tandir`. The receipt address hands any signed-in
customer the order whose number is in the address; the invoice address looks
the same but fetches the order through a helper in another file that only
returns the caller's own orders.

Plumb reported the receipt as **Supported** and cleared the invoice as
**Rejected**, citing the helper's check. The run made 28 requests to the model
and took 15 min 22 s on the measured laptop. These are conclusions from reading
code; that run sent no request to the app.

## Download the Windows package

The easiest way in: a ZIP with Python, Node and the browser view inside, so
nothing else has to be installed first. Get it from
[Releases](https://github.com/ioa2205/plumb/releases).

1. Extract the ZIP anywhere. Folder names with spaces are fine.
2. Double-click **Start Plumb.cmd** for the browser view, or open PowerShell in
   the extracted folder and use `.\plumb.cmd`.
3. Preview, then install, the pinned AI model, the program that runs it and a
   pattern scanner (about 1.5 GB in all; the model comes from Hugging Face):

```powershell
.\plumb.cmd setup
.\plumb.cmd setup --install --approve-large-downloads
.\plumb.cmd inspect .\app\labs\tandir
.\plumb.cmd doctor
```

To map a project without the AI model, use
`.\plumb.cmd setup --install --inspect-only` instead: it sets up source mapping
and downloads no model.

The package was built on 10 October 2026 from the code in this repository. The
commands under "Run from source" work in it too: write `.\plumb.cmd` in place of
`uv run plumb`.

It has been checked only on the laptop it was built on, under that laptop's
Windows account. The model was already installed there, so those checks
downloaded nothing and loaded no AI model. A fresh Windows account and a second
computer have not been tested.

## Run from source

You need Windows 10 or 11 (64-bit), Git, [uv](https://docs.astral.sh/uv/),
Node.js 24 or newer, and pnpm. On macOS or Linux each `plumb` command prints one
sentence saying it is not supported yet.
uv fetches Python 3.12 by itself. Setup does not install these tools.

```powershell
git clone https://github.com/ioa2205/plumb
cd plumb
uv sync --locked
uv run --locked plumb setup                       # preview only; installs nothing
uv run --locked plumb setup --install --approve-large-downloads
uv run plumb inspect labs/tandir                  # map the practice app; no model
uv run plumb doctor                               # hardware, files and free memory
```

On another Windows computer, run the review command below without
`--profile mx350-vulkan-8k`. Plumb then uses `cpu-8k`, and the first review
begins with a check of the model runner that takes a few minutes.

On the measured laptop, repeat the recorded review and open its report:

```powershell
uv run plumb review labs/tandir --resource Order --route '/orders/{order_id}/receipt' --route '/orders/{order_id}/invoice' --family authorization --profile mx350-vulkan-8k --limit 2
uv run plumb report <run-id> --open
```

The browser view has to be built once from source:

```powershell
pnpm --dir frontend install --frozen-lockfile --ignore-scripts
pnpm --dir frontend build
uv run plumb web
```

To review your own project, give the full path of a project you own or are
allowed to test:

```powershell
uv run plumb inspect '<full-path-to-your-project>'
uv run plumb review '<full-path-to-your-project>' --limit 5
```

The limit counts questions, not model requests. Ctrl+C pauses at the next
checkpoint, and `uv run plumb resume <run-id>` continues from the same frozen
copy of the code.

## Install with an AI coding agent

Claude Code, Codex and similar agents can run the steps above. The instructions
written for them, with the rules they must follow (no administrator rights, no
running reviewed code, ask before downloads over 500 MB), are in
[AGENT_INSTALL.md](AGENT_INSTALL.md).

## How Plumb treats your computer

- Reviewed code is read as text. It is never imported, installed or executed.
- There is no cloud model: no API keys, no remote model calls.
- Memory is checked before every launch, and Plumb refuses to start below the
  measured requirement. A watcher stops Plumb's own model if memory runs short;
  it never closes other programs.
- Comments and names are never accepted as evidence.
- Data, models and reports live outside the project being reviewed, by default
  in `%LOCALAPPDATA%\Plumb\data`; set `PLUMB_DATA_DIR` to use another disk.

## What is in this repository

| Folder | What it holds |
| --- | --- |
| `backend/` | Command line, local API, setup, reports, model runner and memory checks |
| `analysis/` | Snapshots, indexing, Python and TypeScript resolution, FastAPI and Next.js mapping |
| `agent/` | Questions to the model, evidence handling and the validator |
| `verification/` | The pinned runtime probe for the bundled practice app only |
| `frontend/` | The browser view (Next.js static export) |
| `eval/` | Development evaluation tools and fixtures |
| `labs/tandir/` | Tandir, the practice app with planted flaws and protected lookalikes |
| `landing/` | The project website, built from the saved records |

Run the tests with `uv run pytest`, after the setup step (it installs the
TypeScript helper that the analysis tests use). In a fresh clone 38 tests are
skipped, each because it needs something this repository does not contain:

- saved evaluation records, which are kept private for now;
- the practice app's prepared, hash-pinned runner environment.

Each skipped test prints which of the two it needs. A few more are skipped on
Windows accounts that may not create symbolic links. Checked on 10 October 2026
by running the whole suite in a fresh clone of a copy made the way this
repository is published, on the development laptop: 2,342 tests passed, 41 were
skipped (the 38 above and 3 for symbolic links) and none failed. Design notes
are private too, so a few code comments refer to documents that are not in this
repository.

## Licence

Plumb's own code is released under the [MIT licence](LICENSE). The AI model
(Qwen3.5-2B, Apache-2.0) and llama.cpp (MIT) are downloaded separately by setup,
after it shows their sources and licences. The Windows package keeps the
licences of the Python and Node runtimes and every bundled dependency.

## Author

Built by Ibodulloxon. Telegram [@ibodullo](https://t.me/ibodullo) ·
[LinkedIn](https://www.linkedin.com/in/ibodullo) · [GitHub](https://github.com/ioa2205)
