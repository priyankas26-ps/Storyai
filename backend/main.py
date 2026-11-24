
import os
import uuid
import io
from datetime import datetime, timezone
from typing import Literal
from xml.sax.saxutils import escape

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from pymongo.errors import PyMongoError
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

from database import db
from ai_service import generate_questions, grade, MODEL, ask_json


app = FastAPI(
    title="StoryAI Pro API",
    version="1.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        os.getenv("FRONTEND_URL", "http://localhost:5173")
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


# -----------------------------
# REQUEST MODELS
# -----------------------------

class StoryDraft(BaseModel):
    title: str = Field(min_length=3, max_length=150)
    story_text: str = Field(min_length=100, max_length=20000)
    creator_name: str = Field(min_length=2, max_length=100)
    count: Literal[5, 10, 15] = 5
    difficulty: Literal["Easy", "Medium", "Hard"] = "Medium"


class Publish(BaseModel):
    questions: list[dict]


class Attempt(BaseModel):
    learner_name: str = Field(min_length=2, max_length=100)
    learner_id: str = Field(min_length=1, max_length=80)
    answers: dict[str, str]


class WritePrompt(BaseModel):
    topic: str = Field(min_length=3, max_length=300)
    genre: str = "Adventure"


# -----------------------------
# DATABASE HELPERS
# -----------------------------

def fetch_story(sid):
    doc = db().stories.find_one(
        {"story_id": sid},
        {"_id": 0}
    )

    if not doc:
        raise HTTPException(
            status_code=404,
            detail="Story ID not found"
        )

    return doc


def fetch_report(rid):
    doc = db().reports.find_one(
        {"report_id": rid},
        {"_id": 0}
    )

    if not doc:
        raise HTTPException(
            status_code=404,
            detail="Report not found"
        )

    return doc


# -----------------------------
# HEALTH CHECK
# -----------------------------

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "model": MODEL,
        "ai_provider": "Ollama",
        "application": "StoryAI Pro"
    }


# -----------------------------
# CREATE STORY AND QUESTIONS
# -----------------------------

@app.post("/api/stories")
def create_story(payload: StoryDraft):

    if len(payload.story_text.split()) < 60:
        raise HTTPException(
            status_code=422,
            detail="Story should contain at least 60 words"
        )

    try:
        questions = generate_questions(
            payload.story_text,
            payload.count,
            payload.difficulty
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Question generation failed: {exc}"
        )

    story = {
        "story_id": uuid.uuid4().hex[:8].upper(),
        "title": payload.title.strip(),
        "story_text": payload.story_text.strip(),
        "creator_name": payload.creator_name.strip(),
        "difficulty": payload.difficulty,
        "status": "draft",
        "questions": questions,
        "model_used": MODEL,
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    try:
        db().stories.insert_one(story)
    except PyMongoError:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable; story was not saved"
        )

    story.pop("_id", None)

    return story


# -----------------------------
# LIST STORIES
# -----------------------------

@app.get("/api/stories")
def list_stories():
    try:
        return list(
            db().stories.find(
                {},
                {"_id": 0, "story_text": 0}
            ).sort("created_at", -1).limit(100)
        )
    except PyMongoError:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable"
        )


# -----------------------------
# GET SINGLE STORY
# -----------------------------

@app.get("/api/stories/{sid}")
def get_story(sid: str):
    try:
        return fetch_story(sid.upper())
    except PyMongoError:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable"
        )


# -----------------------------
# PUBLISH ASSESSMENT
# -----------------------------

@app.put("/api/stories/{sid}/publish")
def publish(sid: str, payload: Publish):

    sid = sid.upper()

    try:
        story = fetch_story(sid)

        if story["status"] == "published":
            raise HTTPException(
                status_code=409,
                detail="Published assessments cannot be edited"
            )

        original = story["questions"]

        if len(payload.questions) != len(original):
            raise HTTPException(
                status_code=422,
                detail="Question count cannot change during review"
            )

        updated = []

        for old, new in zip(original, payload.questions):

            if (
                not isinstance(new.get("question"), str)
                or not new["question"].strip()
                or not isinstance(new.get("reference_answer"), str)
                or not new["reference_answer"].strip()
            ):
                raise HTTPException(
                    status_code=422,
                    detail="Questions and reference answers are required"
                )

            rubric = new.get("rubric")
            maximum = new.get("max_marks")

            if (
                not isinstance(maximum, int)
                or isinstance(maximum, bool)
                or not 1 <= maximum <= 5
                or not isinstance(rubric, list)
                or not rubric
                or any(not isinstance(r, dict) for r in rubric)
                or any(
                    not isinstance(r.get("marks"), int)
                    or isinstance(r.get("marks"), bool)
                    or r["marks"] < 0
                    or not isinstance(r.get("criterion"), str)
                    or not r["criterion"].strip()
                    for r in rubric
                )
                or sum(r["marks"] for r in rubric) != maximum
            ):
                raise HTTPException(
                    status_code=422,
                    detail="Rubric marks must add up to maximum marks (1–5)"
                )

            updated.append({
                "question_id": old["question_id"],
                "question": new["question"].strip(),
                "reference_answer": new["reference_answer"].strip(),
                "rubric": rubric,
                "max_marks": maximum,
                "type": str(new.get("type", "short_answer"))
            })

        update_result = db().stories.update_one(
            {"story_id": sid, "status": "draft"},
            {
                "$set": {
                    "questions": updated,
                    "status": "published"
                }
            }
        )

        if update_result.matched_count == 0:
            raise HTTPException(
                status_code=409,
                detail="Assessment is no longer a draft"
            )

        return fetch_story(sid)

    except PyMongoError:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable"
        )


# -----------------------------
# SUBMIT ANSWERS AND GRADE
# -----------------------------

@app.post("/api/stories/{sid}/submit")
def submit(sid: str, payload: Attempt):

    sid = sid.upper()

    try:
        story = fetch_story(sid)

        if story["status"] != "published":
            raise HTTPException(
                status_code=403,
                detail="Story is not published"
            )

        answers = {
            str(k): str(v)[:5000]
            for k, v in payload.answers.items()
        }

        if not any(v.strip() for v in answers.values()):
            raise HTTPException(
                status_code=422,
                detail="Answer at least one question"
            )

        try:
            results = grade(
                story["story_text"],
                story["questions"],
                answers
            )
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"AI evaluation failed; please retry: {exc}"
            )

        total = sum(x["awarded_marks"] for x in results)
        maximum = sum(x["max_marks"] for x in results)

        report = {
            "report_id": uuid.uuid4().hex[:10].upper(),
            "story_id": sid,
            "story_title": story["title"],
            "learner_name": payload.learner_name.strip(),
            "learner_id": payload.learner_id.strip(),
            "results": results,
            "total_marks": total,
            "maximum_marks": maximum,
            "percentage": (
                round(total / maximum * 100, 2)
                if maximum else 0
            ),
            "model_used": MODEL,
            "created_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "notice": (
                "AI marks are estimates; instructors should "
                "review disputed or high-impact results."
            )
        }

        db().reports.insert_one(report)
        report.pop("_id", None)

        return report

    except PyMongoError:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable; report was not saved"
        )


# -----------------------------
# LIST REPORTS
# -----------------------------

@app.get("/api/reports")
def reports():
    try:
        return list(
            db().reports.find(
                {},
                {"_id": 0, "results": 0}
            ).sort("created_at", -1).limit(100)
        )
    except PyMongoError:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable"
        )


# -----------------------------
# GET SINGLE REPORT
# -----------------------------

@app.get("/api/reports/{rid}")
def report(rid: str):
    try:
        return fetch_report(rid.upper())
    except PyMongoError:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable"
        )


# -----------------------------
# DOWNLOAD PDF REPORT
# -----------------------------

@app.get("/api/reports/{rid}/pdf")
def report_pdf(rid: str):

    try:
        report = fetch_report(rid.upper())
    except PyMongoError:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable"
        )

    buffer = io.BytesIO()

    doc = SimpleDocTemplate(buffer)
    styles = getSampleStyleSheet()

    content = [
        Paragraph(
            "StoryAI Pro - Assessment Report",
            styles["Title"]
        ),
        Spacer(1, 16)
    ]

    for key in (
        "learner_name",
        "learner_id",
        "story_title",
        "created_at",
        "model_used"
    ):
        content.append(
            Paragraph(
                f'<b>{key.replace("_", " ").title()}:</b> '
                f'{escape(str(report[key]))}',
                styles["Normal"]
            )
        )

    content.append(Spacer(1, 12))

    content.append(
        Paragraph(
            f'<b>Score: {report["total_marks"]}/'
            f'{report["maximum_marks"]} '
            f'({report["percentage"]}%)</b>',
            styles["Heading2"]
        )
    )

    for item in report["results"]:
        content.extend([
            Paragraph(
                f'<b>Q{item["question_id"]}: '
                f'{escape(item["question"])}</b>',
                styles["Heading3"]
            ),
            Paragraph(
                f'Marks: {item["awarded_marks"]}/'
                f'{item["max_marks"]}',
                styles["Normal"]
            ),
            Paragraph(
                "Feedback: " + escape(item["feedback"]),
                styles["Normal"]
            ),
            Spacer(1, 8)
        ])

    content.append(
        Paragraph(
            escape(report["notice"]),
            styles["Italic"]
        )
    )

    doc.build(content)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition":
                f'attachment; filename="StoryAI-{rid}.pdf"'
        }
    )


# -----------------------------
# AI STORY WRITING WITH OLLAMA
# -----------------------------

@app.post("/api/ai/write")
def write_story(payload: WritePrompt):

    try:
        result = ask_json(
            f"""
Write an original engaging educational story
of 300 to 500 words.

Genre: {payload.genre}
Topic: {payload.topic}

Return a JSON object with:
"title": string
"story_text": string

The story must have a clear beginning,
middle, and ending.
"""
        )

        if (
            not isinstance(result, dict)
            or not isinstance(result.get("title"), str)
            or not result["title"].strip()
            or not isinstance(result.get("story_text"), str)
            or not result["story_text"].strip()
        ):
            raise ValueError("Invalid story format")

        return result

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"AI writing failed: {exc}"
        )
