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
