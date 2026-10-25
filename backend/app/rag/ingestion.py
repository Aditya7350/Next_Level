"""
Step 4: load APPROVED questions into MongoDB Atlas with vector embeddings.

Place at: app/rag/ingestion.py
Install:  pip install pymongo openai python-dotenv     (or: uv add pymongo openai python-dotenv)
Env:      MONGODB_URI, OPENAI_API_KEY   (optional: MONGODB_DB, EMBEDDING_MODEL, EMBEDDING_DIMS)

Run:
  python app/rag/ingestion.py --dry-run                       # no network, shows what would load
  python app/rag/ingestion.py --path data/question_bank.jsonl # embed + upsert + ensure index
  python app/rag/ingestion.py --search "debugging low recall" --difficulty advanced

Requires MongoDB Atlas (cloud, or the local Docker image mongodb/mongodb-atlas-local).
A plain community mongod does not support $vectorSearch.

Idempotent: documents are upserted by question id, and re-embedded only if the
text that gets embedded (or the embedding model) changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

EMBED_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBED_DIMS = int(os.getenv("EMBEDDING_DIMS", "1536"))
DB_NAME = os.getenv("MONGODB_DB", "interview_platform")
COLLECTION = "question_bank"
INDEX_NAME = "question_vector_index"
BATCH = 64


# ---------------------------------------------------------------- data helpers
def load_approved(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return [r for r in rows if r.get("review_status") == "approved"]


def embedding_text(q: dict) -> str:
    """What gets embedded: question plus the concepts it tests, so retrieval can
    match on topic ('chunk overlap') and not only on the question's wording."""
    return (f"{q['topic']} / {q['subtopic']} ({q['difficulty']}): {q['question']} "
            f"Concepts: {'; '.join(q['expected_concepts'])}")


def embed_hash(text: str) -> str:
    return hashlib.sha1(f"{EMBED_MODEL}|{EMBED_DIMS}|{text}".encode()).hexdigest()


# ------------------------------------------------------------------ embeddings
def embed_texts(texts: list[str]) -> list[list[float]]:
    from openai import OpenAI

    client = OpenAI()
    out: list[list[float]] = []
    for i in range(0, len(texts), BATCH):
        resp = client.embeddings.create(
            model=EMBED_MODEL, input=texts[i:i + BATCH], dimensions=EMBED_DIMS
        )
        out.extend(d.embedding for d in resp.data)
    return out


# --------------------------------------------------------------------- mongodb
def get_db():
    from pymongo import MongoClient

    return MongoClient(os.environ["MONGODB_URI"])[DB_NAME]


def ensure_collection_and_index(db) -> None:
    from pymongo.operations import SearchIndexModel

    if COLLECTION not in db.list_collection_names():
        db.create_collection(COLLECTION)
    coll = db[COLLECTION]
    if any(ix["name"] == INDEX_NAME for ix in coll.list_search_indexes()):
        return
    coll.create_search_index(SearchIndexModel(
        name=INDEX_NAME,
        type="vectorSearch",
        definition={"fields": [
            {"type": "vector", "path": "embedding",
             "numDimensions": EMBED_DIMS, "similarity": "cosine"},
            {"type": "filter", "path": "topic"},
            {"type": "filter", "path": "subtopic"},
            {"type": "filter", "path": "difficulty"},
        ]},
    ))
    print(f"Created vector index '{INDEX_NAME}' (it can take a minute to become queryable).")


def ingest(path: Path) -> None:
    from pymongo import ReplaceOne

    approved = load_approved(path)
    if not approved:
        print("No approved questions found. Run the review tool first.")
        return

    db = get_db()
    ensure_collection_and_index(db)
    coll = db[COLLECTION]

    existing = {d["_id"]: d.get("embed_hash")
                for d in coll.find({"_id": {"$in": [q["id"] for q in approved]}}, {"embed_hash": 1})}
    changed = [q for q in approved if existing.get(q["id"]) != embed_hash(embedding_text(q))]
    print(f"{len(approved)} approved, {len(changed)} new or changed (embedding those).")

    if changed:
        vectors = embed_texts([embedding_text(q) for q in changed])
        ops = []
        for q, vec in zip(changed, vectors):
            doc = {k: q[k] for k in (
                "question", "topic", "subtopic", "difficulty", "skills",
                "expected_concepts", "follow_up_topics", "evaluation_criteria", "source")
                if k in q}
            for optional in ("reference_answer", "follow_up_questions"):
                if optional in q:
                    doc[optional] = q[optional]
            doc.update(embedding=vec, embed_hash=embed_hash(embedding_text(q)),
                       embed_model=EMBED_MODEL)
            ops.append(ReplaceOne({"_id": q["id"]}, doc, upsert=True))
        coll.bulk_write(ops)

    missing_ref = sum(1 for q in approved if not q.get("reference_answer"))
    if missing_ref:
        print(f"Warning: {missing_ref} approved question(s) have no reference_answer.")
    print(f"Done. Collection '{COLLECTION}' now has {coll.count_documents({})} documents.")


# ---------------------------------------------------------------------- search
def search_questions(db, query_text: str, k: int = 5, topic: str | None = None,
                     subtopic: str | None = None, difficulty: str | None = None,
                     exclude_ids: list[str] | None = None, with_vectors: bool = False) -> list[dict]:
    """Semantic search over the question bank. This is what the interview engine
    calls to fetch the next question (e.g. query = weak area from the last answer)."""
    exclude_ids = exclude_ids or []
    flt = {name: {"$eq": val} for name, val in
           (("topic", topic), ("subtopic", subtopic), ("difficulty", difficulty)) if val}
    stage: dict = {
        "index": INDEX_NAME,
        "path": "embedding",
        "queryVector": embed_texts([query_text])[0],
        "numCandidates": max(100, k * 20),
        "limit": k + len(exclude_ids),
    }
    if flt:
        stage["filter"] = flt
    pipeline = [
        {"$vectorSearch": stage},
        {"$addFields": {"score": {"$meta": "vectorSearchScore"}}},
        {"$match": {"_id": {"$nin": exclude_ids}}},
        {"$limit": k},
        {"$project": {"embed_hash": 0} if with_vectors else {"embedding": 0, "embed_hash": 0}},
    ]
    return list(db[COLLECTION].aggregate(pipeline))


# ------------------------------------------------------------------------ main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", type=Path, default=Path("data/question_bank.jsonl"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--search", help="run a test query instead of ingesting")
    ap.add_argument("--topic")
    ap.add_argument("--subtopic")
    ap.add_argument("--difficulty")
    ap.add_argument("-k", type=int, default=5)
    args = ap.parse_args()

    if args.search:
        for hit in search_questions(get_db(), args.search, args.k,
                                    args.topic, args.subtopic, args.difficulty):
            print(f"{hit['score']:.3f}  [{hit['difficulty'][:3]}] {hit['subtopic']}: {hit['question']}")
        return

    if args.dry_run:
        approved = load_approved(args.path)
        print(f"{len(approved)} approved question(s) would be ingested.")
        for (sub, diff), n in sorted(Counter((q["subtopic"], q["difficulty"]) for q in approved).items()):
            print(f"  {sub:<22}{diff:<14}{n}")
        return

    ingest(args.path)


if __name__ == "__main__":
    main()