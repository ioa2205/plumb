# Plumb landing site

A static site that explains Plumb to readers who are new to AI and security.
The overview opens with a picture of the flaw Plumb looks for (one customer
changes a number in the address and sees another customer's receipt), then says
what Plumb does, what it does not do and what nobody knows yet, how it works,
what using it looks like (the recorded terminal output and the saved report),
and whether you can use it today. Other pages cover the recorded run, strengths
and limits, installation, installation by an AI coding agent, and contact. It
is written in English and Uzbek. It is separate from the workbench in
`frontend/` and shares only its design tokens and typefaces.

There are no dependencies and no framework. Pages are plain modules that turn
one extracted record into HTML. Node.js 22 or later is enough.

## The rule this site is built on

**No figure is typed by hand.** `scripts/extract.mjs` reads the saved records in
`docs/results/`, checks them against each other, and writes
`src/data/record.json`. Pages only read that file.

- Code excerpts come from the bundled Tandir lab and are accepted only when they
  hash to the value the saved report cites.
- The four report files are published byte for byte; their hashes must match the
  run record.
- Extraction refuses to write anything that looks private (absolute paths, user
  names, the private brief).
- Where a sentence depends on a recorded value, the page asserts it with
  `holds(...)`, so a changed record stops the build instead of leaving stale prose.
- Source conclusions and runtime observations come from different records and
  are never merged. The recorded run's runtime label is "not attempted".
- The terminal output on the overview is the review's console, line by line.
  The laptop's data folder is replaced by a labelled placeholder; repeated lines
  are shown once with a count, and three long stretches are cut with a note
  saying how many lines went.
- The picture of the flaw uses the practice app's own sample customers, read
  from its seed file, and shows only the fields its receipt route returns.
- The second profile, `cpu-8k`, has its own record
  (`docs/results/2026-10-10-a1-cpu-profile-attempt-2.json`), checked against the
  first-use check and the report it points to. It is a later review of the same
  two addresses and is never merged with the recorded run. Its timings are not
  extracted, because the record says they are not comparable. Its day is the
  one the record is filed under (the laptop's calendar day); the other dates on
  the site are read in UTC.
- The label Plumb prints beside models other than the default is read from
  `backend/profiles.py` and shown as recorded. The models have not been
  compared, so no page may rank them; a check refuses wording that does.

On the page, the monospaced face marks text copied from a record.

## Commands

Run from this folder (PowerShell or Git Bash):

```text
node scripts/extract.mjs            # records -> src/data, tokens, fonts, saved reports
node scripts/extract.mjs --check    # fail if the committed output is out of date
node scripts/build.mjs              # build both languages into dist/
node scripts/build.mjs --release    # also require contact details and the public URL
node --test scripts/*.test.mjs      # record, privacy, policy, language, link and message checks
node scripts/serve.mjs              # preview on http://127.0.0.1:4173 with deployment headers
node scripts/report-images.mjs      # pictures of the saved report (needs the preview and Chrome)
```

Extraction needs the whole repository. Building, testing and serving need only
this folder, which is all a deployment uploads.

## Two languages

Each page module in `src/pages/` renders once per language. English lives at
`/…` and Uzbek at `/uz/…`.

- Wording is written side by side with `t(english, uzbek)` from `src/lib/lang.mjs`.
  A missing Uzbek string stops the build.
- Links are written once, in their English form; `layout.mjs` adds the `/uz`
  prefix on Uzbek pages.
- Text copied from a record (report notes, limitations, refusal messages) stays
  in English in both languages and is marked `lang="en"`. Translating it would
  make it stop being a copy.
- Uzbek uses `‘` (o‘, g‘) and `’` (tutuq belgisi). The self-hosted Latin subset
  of the typeface has those marks and lacks U+02BB and U+02BC. A check refuses a
  straight apostrophe inside an Uzbek word.
- Numbers and dates follow the language: `1.36 GB` and `8 October 2026` in
  English, `1,36 GB` and `2026-yil 8-oktabr` in Uzbek.
- Uzbek uses one set of plain terms throughout: *manzil* for a route, *jonli
  sinov* for a runtime check, *koddan chiqarilgan xulosa* for a source finding,
  *SI modeli* for the AI model. The practice app's people keep their names
  (Alice, Bob), as in its data.

The header has a language menu (the current flag; it opens a list of languages
by their own names) and one day/night switch. With nothing chosen the page
follows the device. A click chooses the other mode; choosing the mode the
device already shows hands control back to the device. Without scripts the
menu still opens and the page follows the device.

## The message form

`/contact` posts to `/api/message`. In the deployment that is the function in
`api/message.js`; its logic and checks are in `server/message.mjs`, which the
preview server uses too. It passes the message to the owner's Telegram through a
bot and stores nothing.

It needs two environment variables in the deployment and nothing in this
repository:

```text
TELEGRAM_BOT_TOKEN   from @BotFather
TELEGRAM_CHAT_ID     the owner's chat with that bot
```

Without them the deployed endpoint answers "not configured" and the page points
to the direct links instead. The local preview accepts a message without sending
it and says so on the page. Set both variables before starting
`node scripts/serve.mjs` to send for real from the preview.

Protections: same-origin requests only, a hidden field that only scripts fill
in, length limits, plain text with control characters removed, and a small
in-memory rate limit. The rate limit resets when the function instance is
recycled; it slows floods and is not a guarantee. Without scripts the form still
posts and lands on `/contact/sent` or `/contact/not-sent`.

The fields have no drawn edge: no ring and no underline. Each is a `well` on
the form's sheet, set apart by tone, with its label directly above and the ink
focus ring when it is being typed in. The owner asked for the border line to go
(10 October 2026), so do not bring back the input underline that `design.md` §6
describes for the workbench.

## Words that must never be published

`scripts/private.mjs` holds the general privacy patterns (absolute Windows
paths, user folders, the local data folder). Words that would identify the
owner live in `landing/.private-words`, one regular expression per line, which
Git ignores: publishing this code must not publish the words it guards
against. Extraction and the privacy check use both when the file is present and
the general patterns alone when it is not.

## The download

When `site.json` has a `download` link, the install page leads with it and the
overview says Plumb can be downloaded. The size, file count and SHA-256 shown
come from the saved package checks (`docs/results/2026-10-09-m7.9b-package-*`),
which extraction refuses unless the archive checks passed, the source was
clean, the recorded report opened, and the investigator files match the
package used in the recorded run.

The download is older than the source code. It was built before the audit
fixes: it has one profile, so it starts a review only on the measured laptop
model, and it lacks `calibrate`, `--model`, the model advice in `doctor`, the
scanner step of setup and the fix that keeps programs in the working folder
from being started. Pages keep "the download" and "from source" apart and never
describe the package as having those changes. Extraction records that the
package's investigator has no `backend/cpu_profile.py`, and pages assert it
with `holds(...)`, so a newer package stops the build until the wording is
revisited.

## Installing, for people and for AI agents

The install steps are written once, in `src/lib/guide.mjs`. `/install` shows
them to people, `/install/agent` turns them into one message to paste into an
AI coding agent (in English; the Uzbek page asks the agent to explain in
Uzbek), and the build writes them to `dist/agent-install.md` for agents that
read web pages. A check keeps the rules and commands the same in all three.
Download sizes come from the pinned model, the pinned program that runs it for
each profile, and the pinned pattern scanner. The source steps leave the
profile option out of the review command, so Plumb picks the profile for the
computer it is on; the package steps keep the recorded command, which names the
only profile the package has.

## Pictures of the saved report

`public/shots/report-*.webp` are captures of `/saved-report/report.html`, in
both themes, taken by `scripts/report-images.mjs`. They are pictures of the
published file, never mock-ups. Take them again whenever the saved report
changes.

## Looking at pages before calling UI work done

Headless Chrome on Windows will not lay out narrower than about 500 px, so
captures go through an iframe harness. Start a second server that permits
framing, then capture a region:

```text
node scripts/serve.mjs --port 4174 --allow-framing
node scripts/shots.mjs uz/recorded-run --width 390 --theme night --y 1200 --height 844
```

Images are written to `shots/`, which Git ignores. Check 1440 and 390 px in Day
and Night, in both languages.

## What to edit

| To change | Edit |
| --- | --- |
| Contact details, public URL, repository and download links | `src/data/site.json` |
| Wording, in either language | `src/pages/*.mjs` and `src/components/*.mjs` |
| Install steps, the agent message and `agent-install.md` | `src/lib/guide.mjs` |
| Layout and type | `src/styles/site.css` (colours come only from generated `tokens.css`) |
| Which facts are available | `scripts/extract.mjs`, then run it |

`site.json` holds the only hand-maintained facts:

```json
{
  "url": "https://example.vercel.app",
  "repository": "https://github.com/owner/name",
  "download": "",
  "author": "Name as it should appear",
  "contact": [{ "label": "Telegram", "value": "@name", "href": "https://t.me/name" }]
}
```

`repository` and `download` may stay empty; the pages then say that the code or
the package is available on request. A release build fails while `contact`,
`author` or `url` is empty.

## Deployment

`vercel.json` builds with `node scripts/build.mjs --release` and serves `dist/`.
It sets a strict content-security policy: pages use no inline style or script,
load nothing from other servers, and may post only to this site. The saved
report under `/saved-report/` keeps its own embedded policy and is marked
`noindex`.

Deploy from this folder so nothing outside it is uploaded. Deployment needs the
owner's approval.

The site is the Vercel project `plumb-security`, live at
https://plumb-security.vercel.app (the `url` in `site.json`). `.vercelignore`
keeps the private word list, the CLI's link and environment files, local
captures and build output out of the upload; its paths are anchored so
`public/shots` is still sent. `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are
encrypted production variables in that project. To publish a change:

```text
node scripts/build.mjs --release && node --test scripts/*.test.mjs
vercel deploy --prod
```
