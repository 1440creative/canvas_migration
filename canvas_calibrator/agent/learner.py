# canvas_calibrator/agent/learner.py
"""
Learner agent: for each question, retrieve relevant chunks and ask Claude
to answer using only the provided course material.
"""
from __future__ import annotations

import json
import logging
import os
import re
import string
from dataclasses import dataclass, field
from typing import Any, Optional

from canvas_calibrator.rag.retriever import Retriever, RetrievedChunk

log = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-20250514"

SYSTEM_PROMPT = """You are a student who has read only the provided course excerpts.
Answer the following question using ONLY the provided material.
Do not use outside knowledge.

Respond in JSON:
{
  "chosen_answer": "<exact text of your chosen answer>",
  "confidence": "high|medium|low",
  "reasoning": "<1-3 sentences explaining which excerpt supports your answer>",
  "found_in_material": true|false,
  "supporting_excerpt": "<the specific phrase or sentence from the material that supports your answer, or null>"
}"""


@dataclass
class QuestionResult:
    verdict: str                        # "correct" | "wrong" | "unsupported"
    question: dict[str, Any]
    agent_answer: str
    correct_answer: str
    confidence: str
    reasoning: str
    supporting_excerpt: Optional[str]
    retrieved_chunks: list[dict[str, Any]]


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation for comparison."""
    return text.lower().translate(str.maketrans("", "", string.punctuation)).strip()


def _build_user_message(question: dict[str, Any], chunks: list[RetrievedChunk]) -> str:
    context_parts = []
    for i, rc in enumerate(chunks, 1):
        context_parts.append(
            f"[Excerpt {i} — {rc.chunk.source_type}: {rc.chunk.title}]\n{rc.chunk.text}"
        )
    context = "\n\n".join(context_parts)

    qtype = question["question_type"]

    if qtype == "fill_in_blank":
        prompt_text = (
            f"Fill in the blank:\n{question['definition']}\n\n"
            f"Word bank: {', '.join(question['choices'])}"
        )
    else:
        choices_text = "\n".join(f"  - {c}" for c in question["choices"])
        prompt_text = f"{question['stem']}\n\nChoices:\n{choices_text}"

    return f"COURSE MATERIAL:\n{context}\n\nQUESTION:\n{prompt_text}"


def _parse_agent_response(raw: str) -> dict[str, Any]:
    """Extract JSON from Claude's response, tolerating markdown fences."""
    # Strip markdown code fences if present
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw)
    if match:
        raw = match.group(1)
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        log.warning("Could not parse JSON from agent response: %s", raw[:200])
        return {
            "chosen_answer": "",
            "confidence": "low",
            "reasoning": "Failed to parse response.",
            "found_in_material": False,
            "supporting_excerpt": None,
        }


def run_learner(
    questions: list[dict[str, Any]],
    retriever: Retriever,
    dry_run: bool = False,
    k: int = 8,
) -> list[QuestionResult]:
    """
    Run the learner agent over all questions.

    Args:
        questions:  parsed question dicts from QTI parser
        retriever:  configured Retriever
        dry_run:    if True, skip API calls and return placeholder results
        k:          number of chunks to retrieve per question

    Returns:
        list of QuestionResult
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key and not dry_run:
        raise EnvironmentError("ANTHROPIC_API_KEY environment variable not set")

    client = None
    if not dry_run:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
        except ImportError:
            raise ImportError("anthropic package required. Install with: pip install anthropic")

    results: list[QuestionResult] = []

    for i, question in enumerate(questions):
        log.info(
            "Processing question %d/%d: %s",
            i + 1, len(questions), question.get("definition") or question.get("stem", "")[:60],
        )

        # Build retrieval query
        if question["question_type"] == "fill_in_blank":
            query = f"{question['definition']} {question['correct_answer']}"
        else:
            query = question["stem"]

        # Retrieve chunks
        retrieved = retriever.retrieve(query, k=k)
        retrieved_dicts = [
            {
                "text": rc.chunk.text,
                "source_path": rc.chunk.source_path,
                "similarity_score": rc.similarity_score,
            }
            for rc in retrieved
        ]

        if dry_run:
            results.append(QuestionResult(
                verdict="unsupported",
                question=question,
                agent_answer="(dry-run)",
                correct_answer=question["correct_answer"],
                confidence="low",
                reasoning="Dry run — no API call made.",
                supporting_excerpt=None,
                retrieved_chunks=retrieved_dicts,
            ))
            continue

        user_message = _build_user_message(question, retrieved)

        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=512,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            raw = response.content[0].text
        except Exception as e:
            log.error("API call failed for question %d: %s", i, e)
            results.append(QuestionResult(
                verdict="unsupported",
                question=question,
                agent_answer="(error)",
                correct_answer=question["correct_answer"],
                confidence="low",
                reasoning=f"API error: {e}",
                supporting_excerpt=None,
                retrieved_chunks=retrieved_dicts,
            ))
            continue

        parsed = _parse_agent_response(raw)
        agent_answer = parsed.get("chosen_answer", "")
        confidence = parsed.get("confidence", "low")
        found_in_material = bool(parsed.get("found_in_material", False))
        reasoning = parsed.get("reasoning", "")
        supporting_excerpt = parsed.get("supporting_excerpt")

        correct = _normalize(agent_answer) == _normalize(question["correct_answer"])

        if not found_in_material or (confidence == "low" and not correct):
            verdict = "unsupported"
        elif correct:
            verdict = "correct"
        else:
            verdict = "wrong"

        results.append(QuestionResult(
            verdict=verdict,
            question=question,
            agent_answer=agent_answer,
            correct_answer=question["correct_answer"],
            confidence=confidence,
            reasoning=reasoning,
            supporting_excerpt=supporting_excerpt,
            retrieved_chunks=retrieved_dicts,
        ))

    return results
