---
name: screenshot-html-preview
description: 'Extract HTML from dpx-buttonode-ui.py and take precise full-content screenshots. Use when: updating the web UI Python source and need to regenerate HTML previews and screenshots, screenshotting the dpx-buttonode-ui preview pages, capturing updated HTML mockups. Covers full workflow: CSS/render function extraction → static HTML generation → pixel-accurate screenshots saved to images/.'
argument-hint: 'Optional: specific tab(s) to regenerate, e.g. "mode devices". Omit to redo all 6.'
---

# dpx-buttonode-ui Preview & Screenshot Skill

Full pipeline: Python source → static HTML mocks → pixel-accurate screenshots → `images/`.

```
.github/skills/screenshot-html-preview/
├── SKILL.md               ← you are here
├── scripts/
│   └── screenshot.js      ← paste into run_playwright_code
└── references/
    └── mock-data.md       ← mock values + Python symbol map
```

---

## When to Run

| Situation | Steps to run |
|---|---|
| Python UI source changed | Part 1 + Part 2 |
| HTML already current, just need fresh screenshots | Part 2 only |

---

## Part 1 — Regenerate HTML Previews

Run this when `src/dpx-buttonode-ui/dpx-buttonode-ui.py` changes.

1. Read the Python file — extract `CSS`, `page()`, and the six `render_*()` functions.  
   See [references/mock-data.md](./references/mock-data.md) for exact line ranges.

2. Build 6 static HTML files in `html/`, one per tab, using hardcoded mock data  
   (no Linux syscalls — no `/sys/`, no `systemctl`).  
   Mock values: see [references/mock-data.md](./references/mock-data.md).

3. **Critical:** remove `min-height:100vh` from the `body` CSS rule in every file.  
   This is the #1 cause of blank space at the bottom of screenshots.

4. Set `class="on"` on the correct nav `<a>` tag for each tab's active state.

### Output

| Tab | File |
|---|---|
| Status | `html/dpx-buttonode-ui-preview.html` |
| Hostname | `html/dpx-buttonode-ui-hostname.html` |
| Network | `html/dpx-buttonode-ui-network.html` |
| Devices | `html/dpx-buttonode-ui-devices.html` |
| Nodes | `html/dpx-buttonode-ui-nodes.html` |
| Mode | `html/dpx-buttonode-ui-mode.html` |

---

## Part 2 — Take Screenshots

1. Open a browser page with `open_browser_page` pointed at any file in `html/`.

2. Paste [scripts/screenshot.js](./scripts/screenshot.js) into `run_playwright_code`.  
   It loops all 6 tabs, measures exact content height per file, and saves to `images/`.

3. Verify: `ls -lh images/*.jpe` — all 6 files should be non-zero and recent.

### Output

| File | Tab |
|---|---|
| `images/001_status.jpe` | Status |
| `images/002_hostname.jpe` | Hostname |
| `images/003_network.jpe` | Network |
| `images/004_devices.jpe` | Devices |
| `images/005_nodes.jpe` | Nodes |
| `images/006_mode.jpe` | Mode |

---

## Troubleshooting

**Blank space at bottom** → `min-height:100vh` still present in the HTML file's `body` rule. Remove it.

**Content cut off** → The `clip` height measurement ran at a viewport ≥ content height. The script sets viewport to 200px first to force overflow — make sure that line isn't removed.

**`file://` URL 403 Forbidden** → File is in `/tmp` or outside the workspace. Keep HTML files in `html/` inside the repo.

**`require is not defined`** → `run_playwright_code` is a restricted Playwright context. No `require`/`import`. Only `page.*` APIs work.

**Images look correct in chat but wrong on disk** → You're viewing the Retina 2x image (1840px wide) in a large viewport. The file is correct — open in Preview.app to verify.
