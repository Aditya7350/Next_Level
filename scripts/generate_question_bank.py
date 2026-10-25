"""
Offline question bank generator for the adaptive interview platform.

Place at: scripts/generate_question_bank.py
Run:      python scripts/generate_question_bank.py --out data/question_bank.jsonl

What it does
  1. Walks a taxonomy (topic -> subtopics) x difficulty levels.
  2. Asks an LLM for questions in the schema from your architecture doc.
  3. Optionally grounds generation in your own reference text (--context-dir).
  4. Dedupes (exact + near-duplicate) and appends to a JSONL file.
  5. Marks every question review_status="pending" so a human approves it
     before it is ever ingested into the vector store.

Provider: uses the OpenAI SDK by default. To use Gemini/Vertex/etc, replace
only the call_llm() function.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

# ----------------------------------------------------------------------------
# 1. Taxonomy: start small (1-2 roles), expand later.
# ----------------------------------------------------------------------------
TAXONOMY: dict[str, list[str]] = {
    "Python": ["data structures", "generators and iterators", "async/await", "decorators", "memory and GIL"],
    "FastAPI": ["dependency injection", "pydantic validation", "auth and security", "background tasks", "testing"],
    "RAG": ["chunking", "embeddings", "vector search", "reranking", "hallucination", "retrieval evaluation"],
    "LLM": ["prompting", "fine-tuning vs RAG", "evaluation", "cost and latency"],
    "System Design": ["scalability", "caching", "databases", "queues and workers"],
    "Behavioral": ["conflict", "ownership", "failure and learning", "teamwork"],
}
DIFFICULTIES = ["basic", "intermediate", "advanced"]

SYSTEM_PROMPT = """You write high-quality technical interview questions.
Return ONLY a JSON object: {"questions": [ ... ]}. No prose, no markdown fences.
Each question object must have exactly these keys:
  question (string, one clear question, no multi-part questions),
  topic (string), subtopic (string), difficulty (basic|intermediate|advanced),
  skills (list of strings),
  expected_concepts (list of 3-6 concepts a good answer covers),
  follow_up_topics (list of 2-4 topics for natural follow-ups),
  evaluation_criteria (list of 2-4 short rubric lines).
Difficulty definitions:
  basic        = a fresher can answer: definitions, simple examples, "when would you use X".
  intermediate = 1-2 years of practice: trade-offs, comparing options, choosing parameters.
  advanced     = production experience: debugging, failure modes, scale, design decisions.
Rules:
- Each question must test the SPECIFIC subtopic given, not RAG/the topic in general.
- Do not start with "What does X stand for" or ask for opinions/predictions about the future.
- Avoid the filler phrase "in the context of". Name the concrete thing instead.
- Prefer scenario questions for intermediate/advanced ("Your system does X; how do you...").
- expected_concepts: 3-6 CONCRETE, specific items a strong answer names (techniques, tools,
  metrics, numbers, failure modes), e.g. "fixed-size vs semantic chunking", "10-20% overlap",
  "recall@k". Never generic items like "definition of X" or "importance of X".
- evaluation_criteria: 2-4 checkable statements about the answer, e.g.
  "Mentions at least one concrete trade-off", "Gives a realistic example".
  Never vague traits like "analytical reasoning" or "breadth of knowledge".
- skills: specific tools/technologies/skills (e.g. "FAISS", "BM25", "cross-encoders"),
  not "Natural Language Processing".
- Questions must be distinct, answerable verbally in 2-4 minutes, and technically accurate
  by current industry practice. Do not copy questions from any known website or book."""

# Curated concepts per subtopic. Each generated question must target ONE of these,
# which keeps coverage broad and stops the model from using generic templates.
# Edit freely: this is where your domain knowledge goes. Topics without an entry fall
# back to unconstrained generation.
CONCEPTS: dict[tuple[str, str], list[str]] = {
    ("RAG", "chunking"): [
        "fixed-size vs recursive splitting", "semantic chunking", "chunk overlap",
        "chunk size vs embedding model token limit", "parent-child (small-to-big) retrieval",
        "structure-aware chunking of headings, tables and code", "metadata attached to chunks",
        "re-chunking and re-indexing when documents change",
    ],
    ("RAG", "embeddings"): [
        "choosing an embedding model (domain fit, MTEB)", "embedding dimensions and storage cost",
        "asymmetric query vs document embeddings", "vector normalization, cosine vs dot product",
        "multilingual embeddings", "re-indexing when the embedding model is upgraded",
        "domain-specific fine-tuning of embeddings", "truncation of long inputs",
        "embedding throughput and batching",
    ],
    ("RAG", "vector search"): [
        "exact (flat) vs approximate nearest neighbor search", "HNSW parameters (M, efSearch)",
        "IVF and product quantization", "distance metrics", "metadata filtering (pre vs post filter)",
        "hybrid search with BM25 and dense vectors, reciprocal rank fusion",
        "index updates and deletes", "recall vs latency tuning", "MMR for result diversity",
    ],
    ("RAG", "reranking"): [
        "bi-encoder vs cross-encoder", "candidate pool size (e.g. top-50 to top-5)",
        "reranker latency budget", "reciprocal rank fusion", "off-the-shelf rerankers vs fine-tuned",
        "when a reranker cannot fix low first-stage recall", "evaluating reranker lift with nDCG@k",
        "truncation of long passages", "LLM-based reranking cost",
    ],
    ("RAG", "hallucination"): [
        "grounded prompting with citations", "faithfulness vs answer relevance",
        "refusing to answer when retrieval is weak", "retrieval failure vs generation failure",
        "context stuffing and lost-in-the-middle", "conflicting or outdated sources",
        "temperature and decoding settings", "evaluating with RAGAS or an LLM judge",
        "post-hoc verification and guardrails",
    ],
    ("RAG", "retrieval evaluation"): [
        "building a golden question set", "recall@k and precision@k", "MRR", "nDCG",
        "relevance labeling: human vs LLM judge", "evaluating retrieval separately from generation",
        "offline evaluation vs online A/B testing", "failure analysis by query type",
        "evaluation set drift", "context precision and context recall (RAGAS)",
    ],
}

ANGLES_BY_DIFFICULTY = {
    "basic": [
        "plain-language definition with a concrete example",
        "when would you use it, and when not",
        "simple comparison of two common options",
        "common beginner mistake and how to avoid it",
        "how a wrong choice shows up in results (a concrete symptom)",
    ],
    "intermediate": [
        "trade-off between two named techniques or tools",
        "choose and justify parameters for a stated requirement",
        "which metric(s) you would track and how to interpret them",
        "specific symptom -> likely cause -> fix, unique to THIS subtopic",
        "how it interacts with the next stage of the pipeline",
    ],
    "advanced": [
        "debug a production failure specific to THIS subtopic, naming what you check first",
        "design or tune it for a realistic requirement (use this angle only if the subtopic sits on the live query path)",
        "a realistic failure mode and how you would detect it",
        "evaluate and compare approaches with an offline test plan",
        "a decision between two approaches under a stated constraint",
    ],
}


def build_user_prompt(topic: str, subtopic: str, difficulty: str, n: int,
                      context: str, existing: list[str]) -> str:
    angles = ANGLES_BY_DIFFICULTY[difficulty]
    prompt = (
        f"Generate {n} {difficulty}-level interview questions.\n"
        f"Topic: {topic}\nSubtopic: {subtopic}\n"
        "Each question must use a DIFFERENT angle, chosen from:\n"
        + "\n".join(f"  - {a}" for a in angles)
        + "\nDo NOT begin questions with generic stock openers such as "
          "'Your RAG system is returning irrelevant results'. Make every scenario specific "
          f"to {subtopic} (name the component, symptom and what you would inspect).\n"
          "Every evaluation_criteria item must reference a named concept from "
          "expected_concepts (e.g. 'Names recall@k as the first check'), never "
          "'mentions specific techniques'.\n"
    )
    concepts = CONCEPTS.get((topic, subtopic))
    if concepts:
        prompt += ("\nEach question must target a DIFFERENT concept from this list, and that "
                   "concept must be the first item in its expected_concepts:\n"
                   + "\n".join(f"  - {c}" for c in concepts)
                   + "\nOnly use concepts appropriate to the difficulty level. Be technically "
                     "accurate per current industry practice; do not mention Word2Vec/GloVe "
                     "or treat TF-IDF as embeddings.\n")
    if existing:
        prompt += ("\nThese questions already exist for this subtopic. Do NOT repeat or "
                   "rephrase them; cover different ground:\n"
                   + "\n".join(f"  - {q}" for q in existing[-20:]) + "\n")
    if context:
        prompt += (
            "\nBase the questions and expected_concepts ONLY on the reference material "
            f"below where possible:\n---\n{context[:6000]}\n---\n"
        )
    return prompt


# ----------------------------------------------------------------------------
# 2. LLM call: the only provider-specific part.
# ----------------------------------------------------------------------------
def call_llm(system: str, user: str, model: str, temperature: float = 0.8) -> str:
    from openai import OpenAI  # pip install openai

    client = OpenAI()  # reads OPENAI_API_KEY from the environment
    resp = client.chat.completions.create(
        model=model,
        temperature=temperature,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    return resp.choices[0].message.content or "{}"


# ----------------------------------------------------------------------------
# 3. Validation + dedupe
# ----------------------------------------------------------------------------
REQUIRED = ["question", "topic", "subtopic", "difficulty", "skills",
            "expected_concepts", "follow_up_topics", "evaluation_criteria"]


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", text.lower()).strip()


def tokens(text: str) -> set[str]:
    return set(normalize(text).split())


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def is_valid(q: dict) -> bool:
    if not all(k in q for k in REQUIRED):
        return False
    if q["difficulty"] not in DIFFICULTIES:
        return False
    if not isinstance(q["question"], str) or len(q["question"]) < 15:
        return False
    if not all(isinstance(q[k], list) and q[k] for k in
               ("skills", "expected_concepts", "follow_up_topics", "evaluation_criteria")):
        return False
    text = q["question"].lower()
    if any(b in text for b in ("stand for", "in the next few years", "single parameter",
                               "10,000 queries", "100,000 queries")):
        return False
    vague = ("breadth of knowledge", "innovative thinking", "analytical reasoning",
             "critical thinking", "clarity of", "definition of", "importance of")
    blob = " ".join(q["evaluation_criteria"] + q["expected_concepts"]).lower()
    return not any(v in blob for v in vague)


def is_duplicate(q: dict, existing: list[dict], threshold: float) -> bool:
    qt = tokens(q["question"])
    for e in existing:
        if normalize(e["question"]) == normalize(q["question"]):
            return True
        if jaccard(qt, tokens(e["question"])) >= threshold:
            return True
    return False
    # Upgrade later: compare embeddings (cosine > ~0.9) instead of word overlap.


def make_id(q: dict) -> str:
    return "q_" + hashlib.sha1(normalize(q["question"]).encode()).hexdigest()[:10]


def load_existing(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_context(context_dir: Path | None, topic: str) -> str:
    """Reads <context_dir>/<topic>.txt|md if present (your own notes/docs)."""
    if not context_dir:
        return ""
    for ext in ("txt", "md"):
        p = context_dir / f"{topic.lower().replace(' ', '_')}.{ext}"
        if p.exists():
            return p.read_text(encoding="utf-8")
    return ""


# ----------------------------------------------------------------------------
# 4. Main
# ----------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/question_bank.jsonl")
    ap.add_argument("--model", default=os.getenv("QB_MODEL", "gpt-4o-mini"))
    ap.add_argument("--per-batch", type=int, default=6, help="questions per topic/subtopic/difficulty")
    ap.add_argument("--topics", nargs="*", help="limit to these topics")
    ap.add_argument("--context-dir", type=Path, help="folder of reference notes, e.g. rag.md, python.txt")
    ap.add_argument("--dup-threshold", type=float, default=0.5)
    ap.add_argument("--dry-run", action="store_true", help="print the plan, make no API calls")
    args = ap.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    bank = load_existing(out)
    added = skipped_invalid = skipped_dup = 0

    for topic, subtopics in TAXONOMY.items():
        if args.topics and topic not in args.topics:
            continue
        context = load_context(args.context_dir, topic)
        for sub in subtopics:
            for diff in DIFFICULTIES:
                if args.dry_run:
                    print(f"[plan] {topic} / {sub} / {diff} x{args.per_batch}")
                    continue
                try:
                    raw = call_llm(SYSTEM_PROMPT,
                                   build_user_prompt(topic, sub, diff, args.per_batch, context,
                                     [e["question"] for e in bank if e["subtopic"] == sub]),
                                   args.model)
                    items = json.loads(raw).get("questions", [])
                except Exception as exc:  # network, rate limit, bad JSON
                    print(f"[warn] {topic}/{sub}/{diff} failed: {exc}")
                    continue

                with out.open("a", encoding="utf-8") as f:
                    for q in items:
                        if not is_valid(q):
                            skipped_invalid += 1
                            continue
                        if is_duplicate(q, bank, args.dup_threshold):
                            skipped_dup += 1
                            continue
                        q["id"] = make_id(q)
                        q["source"] = "llm_generated"
                        q["review_status"] = "pending"  # human must approve before ingestion
                        bank.append(q)
                        f.write(json.dumps(q, ensure_ascii=False) + "\n")
                        added += 1
                print(f"[ok] {topic}/{sub}/{diff}: total so far {len(bank)}")

    if not args.dry_run:
        print(f"\nDone. added={added} invalid={skipped_invalid} duplicates={skipped_dup} -> {out}")


if __name__ == "__main__":
    main()