## Import pipeline

**Order:**

1. pages → 2) assignments → 3) quizzes (optionally questions) → 4) files → 5) discussions → 6) modules → 7) course settings (optionally blueprint sync)

**.env keys (required by \`utils/api.py\`):**
CANVAS_SOURCE_URL=
CANVAS_SOURCE_TOKEN=
CANVAS_TARGET_URL=
CANVAS_TARGET_TOKEN=

**Dry run (no API call):**
python scripts/run_import.py \
 --export-root export/data/<SOURCE_ID> \
 --target-course-id <TARGET_ID> \
 --dry-run -v

**Real run**
python scripts/run_import.py \
 --export-root export/data/<SOURCE_ID> \
 --target-course-id <TARGET_ID> \
 --include-quiz-questions \
 --blueprint-sync \
 -vv

## Timestamp Handling (\*\_at fields)

All metadata dataclasses (e.g., PageMeta, ModuleMeta, AssignmentMeta, QuizMeta) normalize Canvas API timestamps automatically at construction time.

Policy

Input format
Canvas returns ISO-8601 strings, sometimes with offsets (e.g. 2025-08-19T10:52:51-07:00), sometimes with Z suffix (…T17:52:51Z), occasionally with fractional seconds.
Importers may also pass through API JSON without modification.

Normalization
On init, each dataclass calls utils.dates.normalize_iso8601():

Converts to UTC.

Drops microseconds (second precision only).

Always emits Z suffix (e.g., 2025-08-19T17:52:51Z).

If a timestamp is None, it stays None.

If a timestamp is naive (no timezone), assume UTC.

Storage format
Always stored as str in the form:

YYYY-MM-DDTHH:MM:SSZ

Rationale

Canvas course instances may run in different local timezones.

Normalizing to UTC Z avoids ambiguous “local midnight” bugs during migrations.

Dropping microseconds makes metadata diffs stable.
