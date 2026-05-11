# Canvas Migration — Next Steps

## 1. Security scan (do first)
- [ ] Scan entire `export/data/target_dump/` before sharing with staff
- Tool: ClamAV or commercial equivalent
- Reason: TARGET server (Instructure) had a recent breach — treat dump as potentially compromised

## 2. PDF generation with TOC per course
- [ ] Assemble exported HTML pages into a PDF per course, in module order
- [ ] Include table of contents driven by `modules.json`
- Feasibility confirmed — metadata is present in the dump

## 3. Course folder rename / index
- [ ] Decide: rename folders to `{course_id}-{course_code}` (destructive) or create symlinks (non-destructive)
- `make_dump_index.py` already covers the human-readable lookup table (`index.xlsx`)
- Renaming deferred — do symlinks first if unsure

## 4. Cross-course HTML navigation
- [ ] Build a top-level `index.html` spanning all 610 courses
- [ ] Allow the full dump to be browsed offline without Canvas
- Extends the single-course `make_site.py` approach to the full account
