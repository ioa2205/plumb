# Plumb landing site

A static site that explains Plumb to readers who are new to AI and security.

The front page is short on purpose: it shows more than it says, and a check
keeps it under 600 words. It opens with a walk-through in four chapters (one
customer changes a digit and sees another customer's receipt, Plumb finds the
one place with no check, it tries to clear the suspect, and a report comes
out), then gives one picture each to why ordinary tests miss this, why the
code stays on the reader's laptop, how far the claims go, and the real saved
report. Detail lives behind it:

| Page | What it holds |
| --- | --- |
| `/how-it-works` | The two ways Plumb looks at an app, the four steps, the real test and the glossary |
| `/what-it-does` | What it does and does not do, the terminal, the workbench, questions, every command, and whether it can be used today |
| `/recorded-run`, `/web-assessment` | The two recorded cases, under one menu entry ("See it work"), each linking to the other |
| `/evidence` | Strengths and limits |
| `/install`, `/install/agent` | Installation, by hand or by an AI coding agent |
| `/contact` | The message form |

Each deeper page opens with three lines "in short". The site is written in
English and Uzbek. It is separate from the workbench in `frontend/` and shares
only its design tokens and typefaces.

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
- The terminal output on `/what-it-does` is the review's console, line by line.
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

- The web-assessment page is built from the one saved collection
  (`docs/results/2026-10-11-tool-assisted/collection.json`): every planned
  request, the account it was sent as and what came back. Extraction refuses it
  unless it stayed on the loopback address, was approved for exactly the plan
  that ran, kept inside its limits and is still waiting for human review. The
  run's port number is left out. Sign-in replies are not kept by Plumb, so those
  rows carry no answer.
- The comparison of four ways of presenting that evidence comes from the saved
  run and its accounting. Extraction refuses it unless every condition ended
  Inconclusive with nothing counted as correct, and planned, run and unrun
  conditions add up. The pages may not say the model reached a verdict; a check
  fails if they do, and another fails if a page that describes sending requests
  stops saying other websites are switched off.
- Web observations are a third kind of evidence. They are never shown as a
  source finding or as a runtime check.
- What `plumb models` and `plumb ask` print is shown from a record made with
  `scripts/console-records.mjs`, which runs the two read-only commands and
  saves their output under `docs/results/`. Neither loads the model.

On the page, the monospaced face marks text copied from a record. The marks
in front of a line (a filled dot, a half, a ring) say how far that part has
been checked: shown working with a saved record, built but not settled, or
absent.

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
node scripts/workbench-images.mjs   # pictures of the workbench, cut from its own view captures
node scripts/console-records.mjs <new-file>   # save what two read-only Plumb commands print
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

When `site.json` has a `download` link, the install page leads with it and
`/what-it-does` says Plumb can be downloaded. The size, file count and SHA-256 shown
come from the saved package checks (`docs/results/2026-10-11-m7.9i-package-*`),
which extraction refuses unless the archive checks passed, the source was
clean, the commands and the browser view passed, and the recorded run's report
opened unchanged. The record's own top-level verdict is not required: as for
every earlier package, `doctor` refuses when too little memory is free and the
report of a run saved by an older version is refused. Extraction records both,
and the limits page says so.

The download is package J, built on 11 October 2026 from the current source. It
holds the same code as the source: the second profile, `calibrate`, `--model`,
the model advice in `doctor`, the scanner step of setup and the fix that keeps
programs in the working folder from being started. Extraction records what
backs that up. The package's own `doctor` and setup preview name those
features. Its investigator files hash to the same values as the files in
the repository today (`investigator_same_as_source`). They differ from the files
that completed the earlier `cpu-8k` review; its success remains historical.
They are no longer the files of the recorded run's package: extraction counts
how many are the same, changed and new. Pages assert all of this with
`holds(...)`, so a change to an investigator file, or a different package,
stops the build until a new package is built or the wording is revisited. The
working-folder fix has no field of its own; it rests on the package matching
the source.

The extracted feature checks require the new conversation/assessment imports,
pinned three-card pack and its separate licence, default baseline and missing
optional-runner refusal. The separate October 11 observation comparison is
validated from saved accounting and remains incomplete with no demonstrated
accuracy improvement; it is never treated as a review of this ZIP.

What the pages must keep saying, because the records say it: the package's
checks loaded no model, so it has not run a review; they downloaded and
installed nothing, because the model was already on the laptop; and it has only
been tried on the laptop it was built on, under the account that built it. The
recorded test used an earlier package, and the `cpu-8k` run was done from
source. A check fails when `/what-it-does`, the install page or the limits page
stops saying so, when a page still describes the earlier package, or when
`site.json` links a package other than the one the records describe.

## Installing, for people and for AI agents

The install steps are written once, in `src/lib/guide.mjs`. `/install` shows
them to people, `/install/agent` turns them into one message to paste into an
AI coding agent (in English; the Uzbek page asks the agent to explain in
Uzbek), and the build writes them to `dist/agent-install.md` for agents that
read web pages. A check keeps the rules and commands the same in all three.
Download sizes come from the pinned model, the pinned program that runs it for
each profile, and the pinned pattern scanner; they are the same for the package
and from source. The package steps on `/install` are the source steps with
`.\plumb.cmd` in place of `uv run plumb` and the bundled practice app's folder.
The steps that fetch the code and its tools are left out, because the package
carries them. Both leave the profile option out of the review command, so Plumb
picks the profile for the computer it is on. A check keeps the two sets of
steps the same.

## Pictures of the saved report

`public/shots/report-*.webp` are captures of `/saved-report/report.html`, in
both themes, taken by `scripts/report-images.mjs`. They are pictures of the
published file, never mock-ups. Take them again whenever the saved report
changes.

## Pictures of the workbench

`public/shots/workbench-*.webp` are regions of the captures that
`frontend/scripts/assessment-ui-images.mjs` makes of the workbench's screens
(in `tmp/improvements-ui-shots/`, which Git ignores). `scripts/workbench-images.mjs`
cuts them and first compares each capture's size with the saved check
(`docs/results/2026-10-11-improvements-ui-checks.json`). Those captures load
display fixtures: a saved run replayed, example values in forms, and stand-in
conversation answers that the screens label as synthetic. The captions say so,
and a check keeps them saying so. Take the pictures again after the workbench's
screens change:

```text
pnpm --dir frontend build
node frontend/scripts/assessment-ui-images.mjs
node landing/scripts/workbench-images.mjs
```

## Motion

Three things move, and none when the reader asks for less motion:

- the plumb bob in the wordmark swings and settles when a page opens;
- the walk-through on the front page plays its four chapters like a short
  film;
- a list of recorded requests arrives row by row when it scrolls into view
  (`data-tape` in `src/components/trace.mjs`, played by `site.js`), with a
  "Play again" button.

Without scripts the lists are simply there. Bars are SVG rectangles sized by
attributes, because the page policy allows no inline style.

### The walk-through

`src/components/film.mjs` draws four scenes from the record: the practice
app's sample customers, the compared places, the cited code line, the three
judgments and the finding. Its `holds(...)` lines stop the build if the record
stops saying what a scene shows.

- **One markup, two presentations.** Without scripts, or with reduced motion,
  the chapters are four panels, each with its drawing in its final state and
  all its captions. With scripts (`can-play` on `<html>`) the same markup
  becomes one stage beside a chapter list. Never add a caption or a drawing
  that exists only in one of the two.
- **Beats.** An element with `data-from="2"` appears at the chapter's second
  beat; one with `data-to="2"` leaves after it. The script only sets
  `data-beat` on the stage and the classes `on` and `was`; every movement
  is a CSS transition in `site.css`. There is one caption per beat.
- **Scale.** A stage is 25em by 23em and takes its type size from its own
  width (`4cqw`), so it scales as a picture would. Keep text inside a stage
  at 0.85em or larger, or it becomes unreadable on a phone.
- **Playing.** It starts when it scrolls into view, waits while it is out of
  view or the tab is hidden, and stops at the end. Chapter titles jump to a
  chapter; there are Pause and Play again buttons. The bob beside the chapter
  list marks how far it has run.
- **No library.** The page policy allows scripts and styles from this site
  only, so the film is plain JavaScript and CSS. Positions set from script go
  through `style.setProperty`, which the policy permits.

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
