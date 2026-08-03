# Start here, Amy — running MFAS on your Mac

This is the complete set-up guide. It assumes **no programming background** and it is written to
be followed in order. When you are done you will have the whole project running on your own
machine, with an AI assistant that knows the project's rules and can do the work with you.

Budget about **an hour** the first time. Most of that is one download.

> **The one thing to understand before you start.**
> You are not "installing an app". You are setting up a **workspace**: a folder of files, plus an
> assistant that reads those files and works inside them. The assistant is not a chatbot you ask
> questions of — it is something that opens your documents, reads them, changes the project, and
> checks its own work. The instructions that make it behave properly are *in the folder*, which
> is why the folder is the important part.

---

## Contents

1. [What you are setting up](#1-what-you-are-setting-up)
2. [Install the three things you need](#2-install-the-three-things-you-need)
3. [Get the project](#3-get-the-project)
4. [Put your source documents in place](#4-put-your-source-documents-in-place)
5. [Switch it on](#5-switch-it-on)
6. [Meet your assistant](#6-meet-your-assistant)
7. [The rules the assistant must never break](#7-the-rules-the-assistant-must-never-break)
8. [What to ask it to do first](#8-what-to-ask-it-to-do-first)
9. [When something goes wrong](#9-when-something-goes-wrong)
10. [Where everything lives](#10-where-everything-lives)

---

## 1. What you are setting up

Four things, and they fit together like this:

```
   YOUR DOCUMENTS                THE PIPELINE                 WHAT COMES OUT
   ─────────────                 ────────────                 ──────────────
   118 PDFs and workbooks   →    reads every page,       →    · the website
   from the Town, the            checks the arithmetic,       · the Excel warehouse
   County, and your own          refuses anything it          · the coverage report
   research                      cannot trace                 · the open questions
                                        ↑
                                 THE ASSISTANT
                                 works inside all of it,
                                 following the rules in
                                 the folder
```

**Nothing is published that cannot be traced to a document and a page.** That is the entire
premise, and the pipeline enforces it — the build **fails** rather than publish a figure it cannot
stand behind. You will see this happen. It is working as designed.

Current size, so you know what "done" looks like: **118 source documents · 24,215 published
figures · 116 automated checks.**

---

## 2. Install the three things you need

Open the app called **Terminal**. It is in `Applications → Utilities → Terminal`, or press
`⌘ Space` and type "Terminal".

You will be typing commands into it. **Copy and paste them** — do not retype. After each one,
press Return and wait for it to finish before starting the next.

> Terminal shows a lot of text while it works. Almost all of it is noise. What matters is whether
> you get an error at the *end*, and I have told you below what a success looks like each time.

### 2a. Xcode Command Line Tools

This gives your Mac the basic developer tools. It is from Apple.

```bash
xcode-select --install
```

A window will pop up. Click **Install** and wait. If it says *"already installed"*, that is fine —
move on.

### 2b. Homebrew

Homebrew installs software. It is the standard way on a Mac.

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

It will ask for your Mac password. **You will not see the characters as you type** — that is
normal, type it and press Return.

At the end it may print two lines starting with `eval` and tell you to run them. **Do run them**,
exactly as shown. Then check it worked:

```bash
brew --version
```

Success looks like `Homebrew 4.x.x`.

### 2c. Python and the tools the project uses

```bash
brew install python@3.12 poppler tesseract git
```

- **Python** runs the pipeline.
- **poppler** reads PDFs.
- **tesseract** reads the *scanned* PDFs — the ones that are photographs of paper.
- **git** downloads and versions the project.

This takes a few minutes. Check it:

```bash
python3 --version && pdftotext -v && tesseract --version && git --version
```

You should get four version numbers and no "command not found".

### 2d. Codex — your assistant

```bash
npm install -g @openai/codex
```

If that says `npm: command not found`, install Node first with `brew install node`, then run it
again.

Then sign in:

```bash
codex
```

It will open a browser to log in. Use your OpenAI account. Once you see a prompt, type `/quit` for
now — we will come back to it.

---

## 3. Get the project

```bash
mkdir -p ~/projects
cd ~/projects
git clone https://github.com/oc-accountability/MFAS.git
cd MFAS
```

You now have the whole project in `~/projects/MFAS`. Have a look at it in Finder:

```bash
open .
```

> **Note on the folder name.** David's machine has this at `~/projects/hoa-funds` for historical
> reasons — "hoa-funds" was the first name and it stuck. The project and the repository are both
> **MFAS**. If you see `hoa-funds` in any older note, it means this same folder.

---

## 4. Put your source documents in place

**This is the step nobody can do for you, and it is the one that makes everything else work.**

The 118 source documents — the audits, the budgets, your workbooks — are **not** in the download.
They are 945 MB, one file is over GitHub's size limit, and several are things you were sent
directly rather than published on a website. So the project ships the *recipe* and you supply the
*ingredients*.

You already have them: it is your Google Drive folder
**"Orange County Efficiency & Accountability Initiative"**.

1. Download that whole folder from Drive to your Mac.
2. Move it — the folder itself, with its name unchanged — into the `sources` folder inside the
   project.

When you are done the path should read exactly:

```
~/projects/MFAS/sources/Orange County Efficiency & Accountability Initiative/
```

You can do this in Finder by dragging. To open the right place:

```bash
mkdir -p ~/projects/MFAS/sources && open ~/projects/MFAS/sources
```

### Check you got it right

```bash
cd ~/projects/MFAS
find sources -type f | wc -l
```

You want a number **over 150** (there are 118 unique documents plus some duplicate copies).
If you get `0`, the folder went to the wrong place.

> **If some documents are missing, that is fine and the project will tell you which.** It never
> guesses. `docs/SOURCES.md` lists every document, its fingerprint, and where it came from.

---

## 5. Switch it on

```bash
cd ~/projects/MFAS
make venv
```

This sets up Python's own private toolbox inside the project — it does not touch the rest of your
Mac. One or two minutes.

Then the real thing:

```bash
make verify
```

**This is the command that matters.** It rebuilds every figure from your documents and then runs
all 116 checks. It takes **10–20 minutes** the first time because it reads roughly 2,500 pages of
PDF, including running character recognition on the scanned ones. Later runs are much faster
because the recognition is cached.

Success looks like this, at the very end:

```
  VERIFIED — full rebuild and every integrity gate passed.
```

**If it stops with an error instead, that is the project doing its job.** It refuses to publish
rather than publish something wrong. Copy the error and give it to your assistant (section 6) —
that is exactly the kind of thing it is for.

### See the website

```bash
make serve
```

Then open **http://127.0.0.1:8771/** in Safari. That is the real site, running on your machine,
built from your documents. Press `Control-C` in Terminal to stop it.

---

## 6. Meet your assistant

From inside the project folder:

```bash
cd ~/projects/MFAS
codex
```

**Codex reads the file `AGENTS.md` in this folder automatically.** That file contains the
project's rules — what may be published, what may never be, and the traps that have cost real
time. You do not have to explain the project to it. It has already read:

| File | What it teaches the assistant |
|---|---|
| `AGENTS.md` | The rules. Read first, automatically. |
| `docs/AGENT_BRIEF.md` | The full doctrine — how to verify, how to work with you |
| `docs/PROVENANCE.md` | Where every figure comes from |
| `docs/COVERAGE.md` | What is loaded and what is still missing |
| `docs/OPEN_QUESTIONS.md` | The register, including what is waiting on you |
| `docs/EXTRACTION_NOTES.md` | How the documents are read, and why scans are hard |

Talk to it in plain English. It is good at being told *what you want*, and it is at its best when
you push back on it.

**A real example of the kind of thing to say:**

> "Build me Schedule 1.0 — what a household actually pays, town and county together, for a
> $500,000 home. Show me where every number comes from. Do not include anything you cannot cite."

---

## 7. The rules the assistant must never break

These are in `AGENTS.md`, so it already knows them. They are here so **you** know them, and can
tell when something has gone wrong.

> ### 1. Never publish a figure that cannot be traced to a document and a page.
> If it cannot be traced, it does not go out. The build fails instead. This is not negotiable and
> it is the only reason anyone should believe this project.

> ### 2. Never read a number out of a scanned page's hidden text.
> A scan carries an invisible text layer that **transposes digits** — the page reads `4,610,003`
> and the hidden text says `460,100,3`. Scans are read by *looking at the image* instead, and a
> recovered figure is published only where its column still adds up exactly to the printed total.

> ### 3. Your workbooks are read, never written.
> The project imports from your files and never edits them. There is an automated test that fails
> the build if that ever changes. Your authored files stay yours.

> ### 4. The website makes no judgments.
> Your principle, in your words: *"it is a Principle that the website doesn't make judgments, of
> what is good or not. Just the facts man! Let the numbers do the talking."* Publish both numbers
> side by side; delete the sentence that hands the reader a conclusion.

> ### 5. Check your own tooling before saying a source is wrong.
> This has come up repeatedly, and **every single time it was our bug, not the document**. Once,
> 122 of your county figures looked unfindable — you were right and the reader was withholding
> whole statements. If the assistant tells you a document is wrong, ask it to prove it.

> ### 6. Never delete or overwrite. Copy first.
> If it wants to replace something, it makes a dated backup first.

---

## 8. What to ask it to do first

In rough order of value. Say these in your own words; you do not need to be precise.

**Get oriented**

- *"Read the coverage report and tell me, in plain English, what is in the warehouse and what is
  missing."*
- *"Show me the ten most important open questions and which ones are waiting on me."*

**The work that is actually queued** — these come from your own decisions and are ready to go:

1. **The service money-flow schedules** — you called this "the heart of the matter". Four
   questions per service: who provides it · who benefits · who pays · how it changed.
   *Start with the library*, because the Chapel Hill funding transition makes it the clearest
   case of funding that actually moved between governments.
2. **The Total Cost of Ownership front door** — your framing. Property tax, sales tax, water,
   sewer, stormwater; town then county then total, one consolidated number.
3. **Load Chapel Hill.** 13 documents are catalogued and ready. This is the real test of whether
   "adding a town is just adding rows" is true.
4. **The remaining source URLs.** 18 of 118 are recorded and verified; the town's website blocks
   automated access, so those need a human with a browser. See section 9.

**Ask it to check itself** — this is the most useful habit you can build:

- *"Revert that fix and show me the test failing, so I know the test actually works."*
- *"You said this is done — prove it. Show me the measurement, not the reasoning."*

---

## 9. When something goes wrong

| What you see | What it means | What to do |
|---|---|---|
| `command not found` | Something in section 2 did not install | Re-run that step |
| `make: command not found` | Xcode tools missing | `xcode-select --install` |
| The build **fails** with a data error | **Working as designed** — it found something it cannot stand behind | Paste the error to your assistant |
| `0 files` in sources | The Drive folder landed in the wrong place | Section 4 |
| A test fails after a change | The change broke a rule | Ask the assistant to explain *which* rule |
| The site shows no numbers | You opened the file directly instead of using `make serve` | Use `make serve` |

**A note on the town's website.** `hillsboroughnc.gov` blocks automated access — it returns
"Access Denied" to any program, including your assistant. **It does not block you.** So when a
document needs to be fetched from there, that is a job for your browser, not the assistant. Save
the file and tell the assistant where you put it; it will fingerprint it and confirm it is the
right one.

---

## 10. Where everything lives

```
~/projects/MFAS/
├── AGENTS.md              ← the rules; your assistant reads this automatically
├── index.html             ← the website itself, one file
├── Makefile               ← the commands (make verify, make serve)
│
├── sources/               ← YOUR DOCUMENTS GO HERE (never uploaded anywhere)
│
├── data/
│   ├── datasets/          ← every extracted figure, as data
│   ├── exports/           ← MFAS_Data_Warehouse.xlsx — 28 tabs, rebuilt every run
│   └── acquisition_manifest.json
│
├── docs/
│   ├── START_HERE_AMY.md  ← this file
│   ├── AGENT_BRIEF.md     ← the full doctrine
│   ├── COVERAGE.md        ← is the warehouse full? regenerated every build
│   ├── PROVENANCE.md      ← where every figure comes from
│   ├── OPEN_QUESTIONS.md  ← the register
│   ├── SOURCES.md         ← every document, its fingerprint, its URL
│   └── DATA_DICTIONARY.md ← what every column means
│
├── etl/                   ← the pipeline, one numbered stage per job
└── tests/                 ← the 116 checks
```

**Two files are worth opening on their own, in Excel or a text editor:**

- `data/exports/MFAS_Data_Warehouse.xlsx` — everything, 28 tabs, in your own schema. Start at the
  `Index` tab. The `Extraction` column tells you *how* each figure was obtained, colour-coded.
- `docs/COVERAGE.md` — the honest answer to "is it actually full?", regenerated on every build so
  it cannot flatter us.

---

## The one habit worth keeping

Before you publish anything, run:

```bash
make verify
```

If it does not end with **VERIFIED**, nothing goes out. That single command is the difference
between a project people can check and a project people have to trust.

---

*Questions, or something here does not match what you see? That is a bug in this document, not in
you — tell David and it gets fixed.*
