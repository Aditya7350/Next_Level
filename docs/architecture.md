# Architecture notes

The MVP request path is versioned under `/api/v1`. Keep route handlers thin: validate input, call a service, and return a schema. Provider and storage integrations belong behind service or repository boundaries.

The adaptive interview loop is divided into three components:

1. `app/ai` evaluates answers and extracts covered or missing concepts.
2. `app/rag` retrieves and ranks candidate questions using interview context and metadata.
3. `app/interview` applies round, difficulty, repetition, and coverage rules to select the next question.

Resume and job-description ingestion, persistence, authentication, and report generation can be added as independent services. Voice, video, and code execution are later phases; candidate code must never run inside the API process.
