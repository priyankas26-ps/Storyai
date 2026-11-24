
import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

# Ollama configuration
MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://127.0.0.1:11434"
).rstrip("/")


def ask_json(prompt):
    """Generate structured JSON using local Ollama."""

    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": MODEL,
                "prompt": (
                    prompt
                    + "\n\nReturn ONLY a valid JSON object. "
                    "Do not include markdown, explanations, "
                    "or text outside the JSON object."
                ),
                "stream": False,
                "format": "json",
                "think": False,
                "options": {
                    "temperature": 0.2,
                    "num_predict": 4096
                }
            },
            timeout=300
        )

        response.raise_for_status()
        data = response.json()

        return json.loads(data["response"])

    except requests.exceptions.RequestException as exc:
        raise RuntimeError(
            f"Unable to connect to Ollama: {exc}"
        ) from exc

    except (KeyError, json.JSONDecodeError) as exc:
        raise ValueError(
            "Ollama returned an invalid JSON response."
        ) from exc


def generate_questions(story, count, difficulty):
    """Generate reading comprehension questions."""

    prompt = f"""
You create reading comprehension assessments.

Only use facts in the story.

Difficulty: {difficulty}

Generate exactly {count} distinct questions.

Mix:
- Short-answer questions
- Inference questions
- Vocabulary questions

Return a JSON object with key "questions".

Each question must contain:
- "question": string
- "reference_answer": string
- "max_marks": integer from 1 to 5
- "rubric": array of objects containing
  "criterion" (string) and "marks" (integer)
- "type": string

The rubric marks must sum to max_marks.

Story:
{json.dumps(story, ensure_ascii=False)}
"""

    data = ask_json(prompt)
    qs = data.get("questions")

    if not isinstance(qs, list) or len(qs) != count:
        raise ValueError(
            "AI returned an unexpected question count. "
            "Please regenerate."
        )

    result = []

    for i, q in enumerate(qs):
        if not isinstance(q, dict):
            raise ValueError("Invalid question from AI")

        marks = q.get("max_marks")

        if (
            not isinstance(marks, int)
            or isinstance(marks, bool)
            or not 1 <= marks <= 5
        ):
            raise ValueError("Invalid question marks from AI")

        rubric = q.get("rubric")

        if (
            not isinstance(rubric, list)
            or not rubric
            or any(not isinstance(x, dict) for x in rubric)
            or any(
                not isinstance(x.get("marks"), int)
                or isinstance(x.get("marks"), bool)
                or x["marks"] < 0
                or not isinstance(x.get("criterion"), str)
                for x in rubric
            )
            or sum(x["marks"] for x in rubric) != marks
        ):
            raise ValueError("Invalid marking rubric from AI")

        if not all(
            isinstance(q.get(k), str) and q[k].strip()
            for k in ("question", "reference_answer")
        ):
            raise ValueError("Incomplete AI question")

        result.append({
            "question_id": i + 1,
            "question": q["question"],
            "reference_answer": q["reference_answer"],
            "max_marks": marks,
            "rubric": rubric,
            "type": str(q.get("type", "short_answer"))
        })

    return result


def grade(story, questions, answers):
    """Grade learner answers using story evidence."""

    question_data = [
        dict(
            q,
            learner_answer=answers.get(
                str(q["question_id"]), ""
            )
        )
        for q in questions
    ]

    prompt = f"""
You are a fair reading-comprehension evaluator.

Evaluate each learner answer using:
- The story
- The reference answer
- The marking rubric

Allow valid paraphrases.
Blank answers receive zero marks.

Return a JSON object with key "results".

Each result must contain:
- "question_id": integer
- "awarded_marks": integer
- "feedback": string
- "evidence_from_story": string

Return exactly one result for every question.
Do not calculate totals.

Story:
{json.dumps(story, ensure_ascii=False)}

Questions and learner answers:
{json.dumps(question_data, ensure_ascii=False)}
"""

    data = ask_json(prompt)
    rows = data.get("results")

    if not isinstance(rows, list) or len(rows) != len(questions):
        raise ValueError(
            "AI grading returned an invalid response"
        )

    by_id = {}

    for row in rows:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("question_id"), int)
            or isinstance(row["question_id"], bool)
            or row["question_id"] in by_id
        ):
            raise ValueError("Invalid grading question IDs")

        by_id[row["question_id"]] = row

    results = []

    for q in questions:
        row = by_id.get(q["question_id"])

        if row is None:
            raise ValueError("Missing grading result")

        score = row.get("awarded_marks")

        if (
            not isinstance(score, int)
            or isinstance(score, bool)
            or not 0 <= score <= q["max_marks"]
        ):
            raise ValueError("AI awarded invalid marks")

        answer = answers.get(str(q["question_id"]), "")

        results.append({
            "question_id": q["question_id"],
            "question": q["question"],
            "answer": answer,
            "reference_answer": q["reference_answer"],
            "awarded_marks": (
                0 if not answer.strip() else score
            ),
            "max_marks": q["max_marks"],
            "feedback": str(row.get("feedback", "")),
            "evidence_from_story": str(
                row.get("evidence_from_story", "")
            )
        })

    return results
