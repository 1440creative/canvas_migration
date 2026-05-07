# Canvas Calibrator

Canvas Calibrator is a course content auditing tool that uses AI to evaluate whether a course's learning materials adequately support the answers to its quiz questions. It simulates a student who reads only the provided course material and attempts to answer each quiz question, then reports on content gaps where students would not be able to find supporting material.

## Overview

The tool fetches quiz questions from Canvas via the New Quizzes Items API, loads course content (pages, PDFs, external URLs), builds a semantic search index, and uses Claude to act as a learner. Each question is answered using only retrieved course material. The result is a calibration report showing which questions are well-supported, which have wrong answers in the material, and which have no material support at all.

## Prerequisites

**Environment variables** (in `.env` or `.env.local`):
```
CANVAS_TARGET_URL=https://sfu.instructure.com
CANVAS_TARGET_TOKEN=<canvas api token>
ANTHROPIC_API_KEY=<claude api key>
```

**Canvas export** for the course must exist under `export/data/cloud/{course_id}/` with:
- `pages/*/index.html` — course pages (required)
- `files/02-learning-materials/**/*.pdf` — PDFs (optional)
- `course/course_metadata.json` — course metadata (optional)

**Python packages:**
```
requests, beautifulsoup4, anthropic, sentence-transformers,
numpy, pypdf, trafilatura, tiktoken
```

## Usage

```bash
python canvas_calibrator/run_calibration.py \
  --course-id <COURSE_ID> \
  --export-dir <PATH_TO_EXPORT> \
  [--output-dir <REPORT_DIR>]
```

**Required arguments:**

| Argument | Description |
|----------|-------------|
| `--course-id` | Canvas course ID (integer) |
| `--export-dir` | Path to exported course directory (e.g. `export/data/cloud/4031`) |

**Optional arguments:**

| Argument | Description |
|----------|-------------|
| `--output-dir` | Where to save reports (default: `canvas_calibrator/reports/`) |
| `--skip-fetch` | Skip fetching external URLs (faster) |
| `--no-pdfs` | Skip PDF ingestion |
| `--rebuild-index` | Force re-embed chunks even if cache exists |
| `--dry-run` | Parse and index only, skip Claude API calls (for testing) |
| `-v / -vv` | Verbosity: INFO / DEBUG |

**Example:**
```bash
python canvas_calibrator/run_calibration.py \
  --course-id 4031 \
  --export-dir export/data/cloud/4031 \
  --output-dir canvas_calibrator/reports \
  --rebuild-index \
  -vv
```

## How It Works

### Pipeline

```
1. Fetch Quiz Questions
   └─> New Quizzes Items API (/api/quiz/v1/courses/{id}/quizzes/{id}/items)

2. Load Course Content
   ├─> Canvas export pages (HTML)
   ├─> PDFs via pypdf
   └─> External URLs via trafilatura

3. Chunk & Embed
   ├─> Split documents into 400-token chunks (50-token overlap)
   └─> Embed with all-MiniLM-L6-v2 (cached to .cache/)

4. Learner Agent + Report
   ├─> For each question: retrieve top-8 chunks via cosine similarity
   ├─> Call Claude with retrieved chunks + question
   ├─> Compare agent answer vs correct answer
   └─> Generate markdown + HTML report
```

### Verdict Logic

Each question gets one of three verdicts:

| Verdict | Meaning |
|---------|---------|
| ✅ Correct | Agent found supporting material and chose the correct answer |
| ❌ Wrong | Agent found material but chose the wrong answer |
| ⚠️ Unsupported | No supporting material found in the course content |

The **calibration score** is the percentage of questions where course material supports the correct answer: `(correct + wrong) / total`. A high score means the course content covers the tested material well.

### Supported Question Types

- Multiple choice
- True/false
- Fill in the blank (one sub-question per blank)
- Categorization (one sub-question per category)

## Output

Reports are saved as both `.md` and `.html` with timestamped filenames:
```
canvas_calibrator/reports/calibration_{COURSE_CODE}_{TIMESTAMP}.md
canvas_calibrator/reports/calibration_{COURSE_CODE}_{TIMESTAMP}.html
```

**Report sections:**
1. Summary table (totals by verdict)
2. Calibration score
3. API usage and cost
4. Unsupported questions (content gaps)
5. Wrong answers (with agent reasoning and supporting excerpt)
6. Correct answers (collapsible)
7. Recommendations

## Configuration

Key parameters (edit source files to change):

| Parameter | Default | Location |
|-----------|---------|----------|
| Chunk size | 400 tokens | `rag/chunker.py` |
| Chunk overlap | 50 tokens | `rag/chunker.py` |
| Retrieval k | 8 chunks | `agent/learner.py` |
| Embedding model | all-MiniLM-L6-v2 | `rag/embedder.py` |
| Claude model | claude-sonnet-4-20250514 | `agent/learner.py` |

## Caching

Embeddings are cached in `.cache/{course_id}_embeddings.npz` and `.pkl`. Subsequent runs reuse the cache unless `--rebuild-index` is passed. This makes re-runs with the same content much faster.

## Cost & Performance

- First run: 2–5 min (embedding generation)
- Subsequent runs: <1 min (cached embeddings)
- API cost: ~$0.05–$0.30 per 100-question course ($3/M input tokens, $15/M output tokens for Sonnet)

## Caveats

- **Scanned PDFs** with <50 chars/page are skipped with a warning.
- **External URL fetching** uses a 10-second timeout; failures are logged but non-fatal.
- **`--dry-run`** marks all questions as unsupported (no API calls made).
- **Canvas internal links** between pages are not followed; only external URLs are fetched.
- Courses with minimal text content (mostly video/media) will show low calibration coverage.

## Directory Structure

```
canvas_calibrator/
├── run_calibration.py        # Entry point
├── parsers/
│   ├── items_reader.py       # New Quizzes Items API parser (primary)
│   └── qti_parser.py         # Legacy QTI ZIP parser (fallback)
├── ingest/
│   └── content_loader.py     # Loads pages, PDFs, external URLs
├── rag/
│   ├── chunker.py            # Document → overlapping token chunks
│   ├── embedder.py           # Embedding generation & cache
│   └── retriever.py          # Cosine similarity top-k search
├── agent/
│   └── learner.py            # Claude learner agent
├── exporters/
│   └── new_quizzes_exporter.py  # Bulk QTI export utility
├── report/
│   └── generator.py          # Markdown + HTML report generation
└── reports/                  # Generated reports
```
