# canvas_calibrator/report/generator.py
"""
Generate calibration_report.md and calibration_report.html from QuestionResults.
"""
from __future__ import annotations

import html as html_lib
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from canvas_calibrator.agent.learner import QuestionResult, MODEL, INPUT_COST_PER_MTOK, OUTPUT_COST_PER_MTOK


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pct(n: int, total: int) -> str:
    if total == 0:
        return "0%"
    return f"{round(100 * n / total)}%"


def _short(text: str, max_len: int = 120) -> str:
    text = (text or "").strip().replace("\n", " ")
    if len(text) > max_len:
        return text[:max_len] + "…"
    return text


def _recommend(result: QuestionResult) -> str:
    term = result.correct_answer
    quiz = result.question.get("quiz_title", "")
    return f'Consider adding a definition of "{term}" to the course readings (referenced in: {quiz}).'


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------

def _build_markdown(
    results: list[QuestionResult],
    course_id: str | int,
    course_code: str,
    quiz_title: str,
    timestamp: str,
) -> str:
    total = len(results)
    correct = [r for r in results if r.verdict == "correct"]
    wrong = [r for r in results if r.verdict == "wrong"]
    unsupported = [r for r in results if r.verdict == "unsupported"]
    calibration_score = _pct(len(correct) + len(wrong), total)  # material covers question

    lines: list[str] = []
    a = lines.append

    a(f"# Course Calibration Report — {course_code}")
    a(f"")
    a(f"**Course:** {course_id} ({course_code}) | **Quizzes:** {quiz_title} | **Generated:** {timestamp}")
    a(f"")
    a(f"---")
    a(f"")
    a(f"## Summary")
    a(f"")
    a(f"| Metric | Count |")
    a(f"|--------|-------|")
    a(f"| Total questions | {total} |")
    a(f"| ✅ Supported & correct | {len(correct)} ({_pct(len(correct), total)}) |")
    a(f"| ❌ Wrong answer chosen | {len(wrong)} ({_pct(len(wrong), total)}) |")
    a(f"| ⚠️ Unsupported by course material | {len(unsupported)} ({_pct(len(unsupported), total)}) |")
    a(f"")
    a(f"## Calibration Score: {calibration_score}")
    a(f"")
    a(f"*(% of questions where course material supports the correct answer)*")
    a(f"")

    # Token / cost summary (only if API calls were made)
    total_in  = sum(r.input_tokens  for r in results)
    total_out = sum(r.output_tokens for r in results)
    if total_in or total_out:
        cost_in  = total_in  / 1_000_000 * INPUT_COST_PER_MTOK
        cost_out = total_out / 1_000_000 * OUTPUT_COST_PER_MTOK
        total_cost = cost_in + cost_out
        a(f"---")
        a(f"")
        a(f"## API Usage")
        a(f"")
        a(f"| | Tokens | Cost (USD) |")
        a(f"|---|---:|---:|")
        a(f"| Input  | {total_in:,} | ${cost_in:.4f} |")
        a(f"| Output | {total_out:,} | ${cost_out:.4f} |")
        a(f"| **Total** | **{total_in + total_out:,}** | **${total_cost:.4f}** |")
        a(f"")
        a(f"*Model: `{MODEL}` — ${INPUT_COST_PER_MTOK:.2f}/M input · ${OUTPUT_COST_PER_MTOK:.2f}/M output*")
        a(f"")

    # Unsupported
    if unsupported:
        a(f"---")
        a(f"")
        a(f"## ⚠️ Unsupported Questions (Content Gaps)")
        a(f"")
        for r in unsupported:
            q = r.question
            definition = _short(q.get("definition") or q.get("stem", ""))
            a(f"- **Correct answer:** `{r.correct_answer}`")
            a(f"  **Question:** {definition}")
            a(f"  **Note:** No supporting material found in course content.")
            a(f"")

    # Wrong
    if wrong:
        a(f"---")
        a(f"")
        a(f"## ❌ Wrong Answers (Possible Ambiguity or Misleading Content)")
        a(f"")
        for r in wrong:
            q = r.question
            definition = _short(q.get("definition") or q.get("stem", ""))
            a(f"- **Question:** {definition}")
            a(f"  **Correct:** `{r.correct_answer}` | **Agent chose:** `{r.agent_answer}`")
            a(f"  **Confidence:** {r.confidence}")
            a(f"  **Reasoning:** {_short(r.reasoning)}")
            if r.supporting_excerpt:
                a(f"  **Excerpt cited:** *\"{_short(r.supporting_excerpt, 200)}\"*")
            a(f"")

    # Correct
    if correct:
        a(f"---")
        a(f"")
        a(f"## ✅ Correct Answers")
        a(f"")
        a(f"<details>")
        a(f"<summary>Show {len(correct)} correct answers</summary>")
        a(f"")
        for r in correct:
            q = r.question
            definition = _short(q.get("definition") or q.get("stem", ""))
            a(f"- **`{r.correct_answer}`** — {definition}")
        a(f"")
        a(f"</details>")
        a(f"")

    # Recommendations
    if unsupported:
        a(f"---")
        a(f"")
        a(f"## Recommendations")
        a(f"")
        seen: set[str] = set()
        for r in unsupported:
            rec = _recommend(r)
            if rec not in seen:
                a(f"- {rec}")
                seen.add(rec)
        a(f"")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML report (wraps markdown content)
# ---------------------------------------------------------------------------

def _md_to_html_naive(md: str) -> str:
    """
    Very simple markdown → HTML conversion for the report.
    Uses html.escape for safety, then applies basic transforms.
    """
    import re

    lines = md.split("\n")
    out: list[str] = []
    in_table = False
    in_details = False

    for line in lines:
        escaped = html_lib.escape(line)

        # Pass through raw HTML tags we inserted (details/summary)
        if line.strip().startswith("<"):
            out.append(line)
            continue

        # Headers
        if line.startswith("### "):
            out.append(f"<h3>{html_lib.escape(line[4:])}</h3>")
        elif line.startswith("## "):
            out.append(f"<h2>{html_lib.escape(line[3:])}</h2>")
        elif line.startswith("# "):
            out.append(f"<h1>{html_lib.escape(line[2:])}</h1>")
        # HR
        elif line.strip() == "---":
            out.append("<hr>")
        # Table header row
        elif line.startswith("|") and "---" in line:
            continue  # skip separator row
        elif line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if not in_table:
                out.append("<table>")
                in_table = True
                # First row = header
                out.append("<tr>" + "".join(f"<th>{html_lib.escape(c)}</th>" for c in cells) + "</tr>")
            else:
                out.append("<tr>" + "".join(f"<td>{html_lib.escape(c)}</td>" for c in cells) + "</tr>")
        else:
            if in_table:
                out.append("</table>")
                in_table = False
            # List items
            if line.startswith("- "):
                content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html_lib.escape(line[2:]))
                content = re.sub(r"`(.+?)`", r"<code>\1</code>", content)
                content = re.sub(r"\*(.+?)\*", r"<em>\1</em>", content)
                out.append(f"<li>{content}</li>")
            elif line.startswith("  ") and line.strip().startswith("**"):
                content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html_lib.escape(line.strip()))
                content = re.sub(r"`(.+?)`", r"<code>\1</code>", content)
                content = re.sub(r"\*(.+?)\*", r"<em>\1</em>", content)
                out.append(f"<p class='indent'>{content}</p>")
            elif line.strip() == "":
                out.append("<br>")
            else:
                content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html_lib.escape(line))
                content = re.sub(r"`(.+?)`", r"<code>\1</code>", content)
                content = re.sub(r"\*(.+?)\*", r"<em>\1</em>", content)
                out.append(f"<p>{content}</p>")

    if in_table:
        out.append("</table>")

    body = "\n".join(out)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Calibration Report</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; color: #222; }}
  h1, h2, h3 {{ margin-top: 1.5rem; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
  th, td {{ border: 1px solid #ddd; padding: 0.5rem 1rem; text-align: left; }}
  th {{ background: #f5f5f5; }}
  code {{ background: #f0f0f0; padding: 0.1rem 0.3rem; border-radius: 3px; font-size: 0.9em; }}
  li {{ margin: 0.4rem 0; }}
  .indent {{ margin-left: 1.5rem; }}
  hr {{ border: none; border-top: 1px solid #ddd; margin: 1.5rem 0; }}
  details summary {{ cursor: pointer; font-weight: bold; }}
</style>
</head>
<body>
{body}
</body>
</html>"""


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_report(
    results: list[QuestionResult],
    course_id: str | int,
    course_code: str,
    quiz_title: str,
    output_dir: Path,
) -> tuple[Path, Path]:
    """
    Write timestamped calibration report files to output_dir.

    Filenames: calibration_{course_code}_{YYYYMMDD-HHMMSS}.md/.html

    Returns:
        (md_path, html_path)
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%d %H:%M UTC")
    file_ts = now.strftime("%Y%m%d-%H%M%S")
    safe_code = course_code.replace("/", "-").replace(" ", "_")

    md_content = _build_markdown(results, course_id, course_code, quiz_title, timestamp)
    html_content = _md_to_html_naive(md_content)

    stem = f"calibration_{safe_code}_{file_ts}"
    md_path = output_dir / f"{stem}.md"
    html_path = output_dir / f"{stem}.html"

    md_path.write_text(md_content, encoding="utf-8")
    html_path.write_text(html_content, encoding="utf-8")

    return md_path, html_path
