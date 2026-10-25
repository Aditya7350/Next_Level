# API guide

The API is available under `/api/v1` (the same routes are also mounted at the root for compatibility). Interactive request examples are available at `/docs`.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/register` | Create an account and return a bearer token |
| POST | `/auth/login` | Authenticate and return a bearer token |
| POST | `/resume/upload` | Upload PDF, DOCX, TXT, or MD resume (8 MB limit) |
| GET | `/resume/{resume_id}` | Get parsed resume content |
| POST | `/jd/analyze` | Extract likely skills from a job description |
| POST | `/interview/create` | Create a personalized interview plan |
| POST | `/interview/{interview_id}/start` | Start the interview and return its first question |
| GET | `/interview/{interview_id}/question` | Get the current question |
| POST | `/interview/{interview_id}/answer` | Evaluate an answer and choose the next question |
| GET | `/interview/{interview_id}/report` | Retrieve the completed interview report |
| GET | `/interview/history` | List the signed-in user's interviews |
| GET | `/dashboard` | Return summary metrics for the signed-in user |
| WS | `/ws/interview/{interview_id}?token={bearer_token}` | Exchange interview questions and answers over WebSocket |
| POST | `/interview/{interview_id}/voice` | Reserved for a configured speech provider (currently 501) |
| POST | `/coding/execute` | Reserved for an isolated code runner (currently 501) |

Except for health checks and account creation/login, HTTP routes require `Authorization: Bearer <access_token>`. In Swagger, use **Authorize** and enter the token returned by registration or login.

## Interview request examples

Create a plan:

```json
{
  "interview_type": "technical",
  "difficulty": "intermediate",
  "question_count": 5
}
```

Submit an answer:

```json
{
  "answer": "I used embeddings and retrieval to ground the generated response in relevant chunks."
}
```

The answer response contains a simple rubric-based evaluation and either the next question or the final report. This is a local baseline; model-backed evaluation and vector retrieval have not been connected yet.

Resume uploads return a heuristic profile with contact details, recognized skills, and text grouped by detected summary, experience, education, project, and certification headings. Scanned image-only PDFs need OCR and are not currently supported.

## Local persistence

Current records and bearer tokens live in process memory. They are cleared when the API process restarts and are not shared between multiple workers. Connect a persistent repository and managed identity/session storage before deploying this as a multi-instance production service.
