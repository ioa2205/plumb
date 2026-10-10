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
- Do not start a review with the AI model, or run plumb calibrate, unless the person asks: both load the model.

## Before you start

- Windows 10 or 11, 64-bit, and PowerShell. On macOS or Linux every `plumb` command prints one sentence saying the system is not supported yet, and stops.
- Git, uv, Node.js 24 or newer, and pnpm. Plumb’s setup does not install them. uv provides Python 3.12.
- For a full review: 1.48 GB of free disk space for the downloads, and enough free memory for the profile Plumb picks. That is `mx350-vulkan-8k` on an Intel Core i5-1135G7 laptop with NVIDIA GeForce MX350 graphics, and `cpu-8k` on any other 64-bit Windows computer with an x64 processor: the same AI model on the processor alone, needing 2.44 GB of free RAM. `cpu-8k` has completed one real run, on the laptop Plumb is developed on. It has not been tried on a second computer, and how fast it is there is not known.
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

Lists what is ready and what is missing, with the size, source and licence of each download, and names the review profile this computer would use. It installs nothing.

```powershell
uv run --locked plumb setup
```

### 5. Install

Show the person the downloads the preview listed (the AI model, 1.40 GB; the program that runs it, 18.6 MB or 32.1 MB depending on the profile; the pattern scanner, 53.7 MB), and run this only after they agree. The last option records their approval; setup refuses downloads over 500 MB without it.

```powershell
uv run --locked plumb setup --install --approve-large-downloads
```

If the person does not agree to the downloads, or the preview says AI review is not available on this system, install only what mapping needs instead. It downloads no AI model.

```powershell
uv run --locked plumb setup --install --inspect-only
```

### 6. Map the practice app

Loads no model. Prints the files, frameworks and addresses Plumb found in the bundled practice app, and saves an overview.

```powershell
uv run plumb inspect labs/tandir
```

### 7. Check the machine

Reads the hardware, the installed files and the free memory, and changes nothing. It names the profile this computer would use and says whether enough memory is free for it. It also names the default AI model and the largest one that fits in the memory free right now. If memory is short, close other programs and run it again.

```powershell
uv run plumb doctor
```

### 8. Optional: check the program that runs the model

Skip this step unless the person asks for it: it loads the AI model. With the cpu-8k profile the first review runs the same check by itself (3 test questions and 10 pairs of requests that look for one answer leaking into the next). It shows that the model runner works on this computer; it does not grade the model’s answers.

```powershell
uv run plumb calibrate
```

### 9. Run the recorded review

Only if the person asks for a review: it loads the AI model. It asks about the receipt and the invoice of the practice app and prints a run ID at the end. Plumb picks the profile for this computer: mx350-vulkan-8k on the measured laptop model, cpu-8k on any other. With cpu-8k, the first review on a computer begins with the check from the step before, unless that check has already passed there. On the measured laptop model the recorded run took 15 min 22 s; how long it takes on another computer is not known.

```powershell
uv run plumb review labs/tandir --resource Order --route '/orders/{order_id}/receipt' --route '/orders/{order_id}/invoice' --family authorization --limit 2
```

### 10. Open the report

Put the run ID that was printed in place of <run-id>. The saved report opens in your browser. No model is loaded.

```powershell
uv run plumb report <run-id> --open
```

### 11. Optional: the browser view

The same saved results in a browser window. From source it has to be built once first. It starts no model. Its final round of browser checks is still pending.

```powershell
pnpm --dir frontend install --frozen-lockfile --ignore-scripts
pnpm --dir frontend build
uv run plumb web
```

## If Plumb refuses

- **Files are missing or unverified.** Read the setup preview and install only the pinned files it lists.
- **No review profile for this computer.** A review with the AI model needs 64-bit Windows on an Intel or AMD processor. On any other system, install with the --inspect-only option instead: mapping with inspect and saved reports work without a profile.
- **Not enough RAM or graphics memory.** Close other programs, run doctor again, then retry or resume. The threshold stays where it is.
- **The program that runs the model failed its first-use check.** Reviews with that profile stay off on this computer until the check passes. Run calibrate to try again. Mapping and saved reports still work.
- **Not enough free disk space.** Free space for the downloads the preview lists, then run setup again. Nothing was installed.
- **No supported checks match.** Plumb names the kinds of check your project does have and the exact option to use, for example --family nextjs_exposure for a project with only Next.js code. If it names none, read the overview to see what it recognised. An empty selection is not a safety verdict.
- **A saved report is refused.** The file was changed, or was written by an older version. Keep it as it is and open it with the version that wrote it.
- **This system is not supported yet.** Plumb runs on 64-bit Windows 10 or 11 only for now. From source, every command on macOS or Linux prints this one sentence and stops.

## What to report at the end

- Which steps passed and which failed, with the exact message of any failure.
- Which review profile the setup preview or doctor names for this computer, and whether doctor says enough memory is free for it.
- What `inspect` found in the practice app: files, frameworks and addresses.
