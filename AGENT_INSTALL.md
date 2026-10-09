# Installing Plumb: instructions for AI coding agents

Plumb is a local security reviewer. It reads a web app’s source code on this computer with a small offline AI model, and reports places where one user can reach another user’s data, citing the exact lines. It is a working prototype for Windows.

Work through the steps in order and explain each result to the person in plain words. Stop and ask the person wherever these instructions say so.

## Rules

- Never use administrator rights, and never change system settings, drivers or Windows features.
- Never run, install or import code from a project that Plumb reviews. Plumb only reads it, and so do you.
- Do not install Git, uv, Node.js or pnpm without asking the person first.
- Keep Plumb’s data folder outside the Plumb folder and outside any project it reviews. The default location is correct.
- Ask the person before any download larger than 500 MB.
- If a command fails or Plumb refuses, show the person the exact message and stop. Do not work around a refusal or lower a limit.
- Do not start a review with the AI model unless the person asks for one.

## Before you start

- 64-bit Windows, and PowerShell.
- Git, uv, Node.js 24 or newer, and pnpm. Plumb’s setup does not install them. uv provides Python 3.12.
- For a full review: the measured hardware profile `mx350-vulkan-8k` (an Intel Core i5-1135G7 with NVIDIA GeForce MX350 graphics), and 1.43 GB of free disk space for the downloads. On any other computer only source mapping is available, and that path has not yet been tried on a second computer.
- The code: https://github.com/ioa2205/plumb

## Steps

### 1. Get the code

This copies the source into a new folder and moves into it.

```powershell
git clone https://github.com/ioa2205/plumb
cd plumb
```

### 2. Check the tools

Each command prints a version number; Node.js must be 24 or newer. If any tool is missing or too old, tell the person which one and stop. Do not install it yourself. Python 3.12 is not on the list because uv fetches it.

```powershell
git --version
uv --version
node --version
pnpm --version
```

### 3. Create Plumb’s environment

Installs Plumb’s own Python packages inside its folder, at exactly the versions it was tested with.

```powershell
uv sync --locked
```

### 4. Preview the setup

Lists what is ready and what is missing, with the size, source and licence of each download, and says whether this computer has a measured profile. It installs nothing.

```powershell
uv run --locked plumb setup
```

### 5. Install

Only if the preview names a measured profile. Show the person the downloads the preview listed (the model, 1.40 GB, and the program that runs it, 32.1 MB), and run this only after they agree. The last option records their approval; setup refuses downloads over 500 MB without it.

```powershell
uv run --locked plumb setup --install --approve-large-downloads
```

On any other computer, install only what mapping needs. Setup refuses the full installation there, because no measured profile exists for that hardware.

```powershell
uv run --locked plumb setup --install --inspect-only
```

### 6. Map the practice app

Loads no model. Prints the files, frameworks and addresses Plumb found in the bundled practice app, and saves an overview.

```powershell
uv run plumb inspect labs/tandir
```

### 7. Check the machine

Reads the hardware, the installed files and the free memory, and changes nothing. If it says memory is short, close other programs and run it again.

```powershell
uv run plumb doctor
```

### 8. Run the recorded review (measured laptop only)

Only on the measured laptop model. It asks the AI model about the receipt and the invoice of the practice app and prints a run ID at the end. The recorded run took 15 min 22 s.

```powershell
uv run plumb review labs/tandir --resource Order --route '/orders/{order_id}/receipt' --route '/orders/{order_id}/invoice' --family authorization --profile mx350-vulkan-8k --limit 2
```

### 9. Open the report (measured laptop only)

Put the run ID that was printed in place of <run-id>. The saved report opens in your browser. No model is loaded.

```powershell
uv run plumb report <run-id> --open
```

### 10. Optional: the browser view

The same saved results in a browser window. From source it has to be built once first. It starts no model. Its final round of browser checks is still pending.

```powershell
pnpm --dir frontend install --frozen-lockfile --ignore-scripts
pnpm --dir frontend build
uv run plumb web
```

## If Plumb refuses

- **Files are missing or unverified.** Read the setup preview and install only the pinned files it lists.
- **No measured hardware profile.** Use inspect and saved reports. A review with the model needs a measured profile for this machine.
- **Not enough RAM or graphics memory.** Close other programs, run doctor again, then retry or resume. The threshold stays where it is.
- **Not enough free disk space.** Free space for the downloads the preview lists, then run setup again. Nothing was installed.
- **No supported checks match.** Read the overview to see what Plumb recognised. An empty selection is not a safety verdict.
- **A saved report is refused.** The file was changed, or was written by an older version. Keep it as it is and open it with the version that wrote it.

## What to report at the end

- Which steps passed and which failed, with the exact message of any failure.
- Whether this computer has a measured review profile, as the setup preview or doctor states it.
- What `inspect` found in the practice app: files, frameworks and addresses.
