# StoryAI Pro

Premium Light full-stack story-based learning and assessment application. React + Tailwind CSS, FastAPI, Gemini, MongoDB.

## Prerequisites
- Python 3.10+; Node.js 18+; MongoDB Atlas connection string (or local MongoDB); Gemini API key.

## Run in VS Code
1. Open the `storyai-pro` folder in VS Code.
2. Terminal 1:
   ```bash
   cd backend
   python -m venv .venv
   # Windows PowerShell: .venv\Scripts\Activate.ps1
   # macOS/Linux: source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Copy `backend/.env.example` to `backend/.env`, then set `GEMINI_API_KEY` and `MONGODB_URI`. Never commit this file.
4. Terminal 1, in `backend` with virtual environment active:
   ```bash
   uvicorn main:app --reload --port 8000
   ```
5. Terminal 2:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```
6. Open http://localhost:5173. API documentation: http://localhost:8000/docs.

## End-to-end demonstration
1. Creator: create a 300–500 word story, select count and difficulty, generate questions.
2. Review questions, answers, rubrics, then publish and copy Story ID or link.
3. Learner: open shared URL (or enter Story ID), read, identify themselves, answer and submit.
4. View marks, feedback, evidence, total and percentage. Download PDF. Refresh to verify persistence.

## Troubleshooting
- `502` on generation/evaluation: check Gemini API key, model access, quota, and internet connection. Your draft stays in the editor unless you reload.
- `503` database unavailable: verify MongoDB is running, Atlas network access and connection URI.
- CORS errors: set `FRONTEND_URL` to the exact Vite origin (default http://localhost:5173).
- npm fails: install a supported Node.js LTS release.
- Python package errors: ensure the backend virtual environment is activated.

## Security and limitations
This is an educational prototype, not a production multi-tenant system. Learner name and student ID are identifiers, **not secure authentication**. Story/report endpoints are not access-controlled. Use fictitious student IDs during demos; do not expose the app publicly with personal data. For production, add authentication, authorization, rate limiting, input sanitization, audit logging, and privacy controls. Gemini assessments may be inaccurate; instructors should review disputed or high-impact grades. Grading uses semantic rubric prompts, validates awarded marks and calculates totals in Python. Published assessments are immutable to preserve grading consistency.

## Team responsibilities
- Student 1: story authoring, generation, review, publication.
- Student 2: story retrieval, assessment submission, reports.
- Both: database, Gemini integration, testing, responsible AI discussion.

## Testing checklist
- Valid and invalid story; 5/10/15 questions; easy/medium/hard; review/edit; publish; open ID; correct/partial/wrong/blank answers; paraphrases; invalid ID; API failure; database outage; restart persistence.

## Attribution
Developed with AI assistance. Review and understand all code before submission. API keys must not be submitted.
