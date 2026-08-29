---
name: update-docs
description: "Update project documentation. Use when: updating README, CHANGELOG, AGENTS.md, VERSION bump, roadmap review, docs audit, release prep, keeping docs in sync with code. Covers: semver bump, changelog entry, readme accuracy, agents.md project block, roadmap grooming."
argument-hint: "Describe what changed, or say 'full audit' to check everything"
---

# update-docs

Full documentation update workflow for dpx_buttonode. Audits and updates README, CHANGELOG, VERSION, AGENTS.md, roadmap, and dpx_release_note_template.

## Related Skills
- **`screenshot-html-preview`** — invoked by Step 3.5 of this skill when the web UI has changed and README screenshots need refreshing. Full procedure in `.github/skills/screenshot-html-preview/SKILL.md`.

## When to Use
- After completing a feature branch or bugfix before opening a PR
- Running a "full audit" to bring all docs in sync with actual code
- Bumping a version and writing the changelog entry
- Updating the AGENTS.md project block after architecture changes
- Grooming the roadmap after a milestone

## Inputs
The skill accepts a free-form argument describing what changed, or `"full audit"` to inspect every doc file and cross-check against the codebase.

## Mode Behavior

| Mode | How to trigger | Behavior |
|------|---------------|----------|
| **Quick** | Argument describes specific changes (e.g. `"bump patch, UI fix"`) | Apply changes immediately, then show a diff summary of everything touched |
| **Full audit** | Argument is `"full audit"` or blank | Read everything first, present a proposed change plan with what will be updated and why, then **ask the user to confirm** before writing anything |

---

## Procedure

### Step 1 — Read Current State
Read these files in parallel before making any changes:
- `VERSION` — current semver string (single source of truth; no `package.json` in this project)
- `CHANGELOG.md` — last entry date and version
- `README.md` — installation paths, Built With list, Usage section, Roadmap
- `AGENTS.md` — PROJECT block (Status, Branch, Version File, Architecture table)
- `dpx_release_note_template.md` — release note format reference
- `ROADMAP.md` — open and completed items

Also do a broad scan of the project's directory tree (excluding `.git/`, build output dirs) to catch any new or removed files, scripts, or workflow components not yet reflected in the docs. Key areas to scan:

| Area | Path |
|------|------|
| Packer definition | `dpx-buttonode.pkr.hcl` |
| Shell scripts | `scripts/` |
| Web UI | `src/dpx-buttonode-ui/` |
| UI preview pages | `html/dpx-buttonode-ui-*.html` |
| GitHub workflows | `.github/workflows/` |
| Skills | `.github/skills/` |

### Step 2 — VERSION Bump (if needed)
Follow semantic versioning strictly:

| Change type | Bump |
|-------------|------|
| Breaking API / incompatible change | MAJOR |
| New feature, backwards-compatible | MINOR |
| Bug fix, docs-only, typo | PATCH |

Rules:
- Write the new version string to `VERSION` (single line, no `v` prefix)
- **`VERSION` is the only version file** — there is no `package.json` to sync
- **Do NOT bump if the user explicitly says not to** or if there are no code changes

### Step 3 — CHANGELOG Entry
Add a new entry above the previous one using [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) format:

```markdown
## [X.Y.Z] - YYYY-MM-DD

### Added
- ...

### Fixed
- ...

### Changed
- ...

### Removed
- ...
```

Rules:
- Today's date is always used (current session date)
- Only include categories that have entries — omit empty ones
- Link issue/PR numbers as `[#N](https://github.com/dubpixel/dpx_buttonode/issues/N)`
- If no version bump: add entry under `## [Unreleased]` instead
- Keep entries factual and precise — what changed and why, not how

### Step 3.5 — UI Screenshot Refresh (conditional)
**Trigger this step if any of the following are true:**
- `src/dpx-buttonode-ui/dpx-buttonode-ui.py` was modified this sprint
- Any `dpx-buttonode-ui-*.html` preview file was modified or regenerated
- The README references UI screenshots and the UI has visually changed
- The user's argument mentions "UI", "screenshots", or "preview"

**What to do:**
Invoke the **`screenshot-html-preview`** skill. Do NOT attempt to take screenshots inline — that skill handles the two-pass viewport measurement required to avoid blank space at the bottom of every frame. The full file map and procedure live in `.github/skills/screenshot-html-preview/SKILL.md`.

Screenshots produced by that skill should be saved to `images/` (the README image convention for this project) and the README `<img>` tags updated to reference the new files.

If this step is not triggered, skip it entirely.

---

### Step 4 — README Accuracy Check
The README uses the dpx Best-README-Template fork v0.5.7. **Never structurally replace it.** Fill in and update only:

- **Tagline / subtitle** — still accurate for current feature set?
- **About `<details>` block** — description matches current architecture?
- **Built With badges** — add any new tech added this sprint; remove placeholder commented badges only if unused
- **Prerequisites table** — reflects current tooling requirements (Packer version, Armbian builder, `qemu-user-static`, etc.)
- **Getting Started paths** — Dev / Docker / Flash paths still accurate?
- **Usage section** — example commands still work?
- **Roadmap** — mark completed items ✅, add new planned items

**Quick mode:** apply and include README changes in the final diff.  
**Full audit mode:** list proposed README changes in the plan and wait for confirmation before writing (AGENTS.md §6).

### Step 5 — AGENTS.md Project Block
Update the `## PROJECT: dpx-buttonode` section in `AGENTS.md`:
- **Status line** — current version + date + ✅ or 🚧
- **Branch line** — current working branch (or `main` if on main)
- **Version File line** — current version number
- **Architecture table** — add any new components, update paths or notes if things moved; reread the intro paragraph too, not just the table rows — it goes stale just as easily (e.g. describing a single build pipeline after a second one was added)
- **Gotchas & Landmines** — this is the step most likely to get skipped, so check it explicitly every time: did this sprint's work involve debugging a non-obvious failure, a wrong assumption that cost real time, or a fix for something that isn't visible just from reading the code? If so, it needs a numbered gotcha entry (bug/error text, root cause, the fix, and the date confirmed live) — not just a CHANGELOG line. CHANGELOG says *what* shipped; a gotcha preserves *why a future agent shouldn't redo the same mistake*. Skim git commit messages and diffs from this sprint's range for `fix:`/`bug`/wording like "confirmed live" as a prompt for what might need one.

Do NOT modify the global directives sections of AGENTS.md (§1 through §6 boilerplate) — only the `## PROJECT` block.

### Step 6 — ROADMAP Grooming
Review `ROADMAP.md`:
- Mark completed items with `[x]`
- Add new planned items discovered during the audit
- Remove or archive items that are no longer relevant

### Step 7 — Release Note (if releasing)
If this is a version tag release (MAJOR or MINOR bump), fill in `dpx_release_note_template.md` with:
- Version, date, one-sentence summary
- Feature list from the CHANGELOG `Added` section
- Fix list from `Fixed`
- Breaking changes if any

### Step 8 — Verification Checklist
Before finishing, confirm:
- [ ] `VERSION` file is updated
- [ ] CHANGELOG has an entry for this version with today's date
- [ ] README Prerequisites and paths are accurate
- [ ] AGENTS.md Status line shows correct version and date
- [ ] AGENTS.md Gotchas & Landmines has an entry for any non-obvious bug/fix from this sprint
- [ ] ROADMAP completed items are checked off
- [ ] No placeholder text left in docs (e.g. `[Project Name]`, `[e.g., ...]`)
- [ ] README confirmed with user before committing (per AGENTS.md §6)

---

## dpx_buttonode Project Conventions

- `VERSION` file is the **single source of truth** — no `package.json` mirrors it
- Branch naming: `feature/description`, `fix/description`, `docs/description`
- Roadmap items use checkboxes: `- [ ]` open, `- [x]` done
- Images referenced in README live in `images/` — do not add hotlinked images
- The dpx fork comment header at the top of README.md must never be removed
- Never commit `.tar.gz`, `.deb`, `.img`, or `.img.gz` files — gitignored by design
- The `buttons-deb-mirror` release tag must never be deleted — it is the CI package source

## Files Touched

| File | What changes |
|------|-------------|
| `VERSION` | Version string |
| `CHANGELOG.md` | New version entry |
| `README.md` | About, Built With, Getting Started, Roadmap |
| `ROADMAP.md` | Item status and new items |
| `AGENTS.md` | PROJECT block only |
| `dpx_release_note_template.md` | Filled in for releases |
| `html/dpx-buttonode-ui-*.html` | Regenerated by screenshot-html-preview skill (Step 3.5) |
| `images/*.png` | Updated screenshots from screenshot-html-preview skill (Step 3.5) |
