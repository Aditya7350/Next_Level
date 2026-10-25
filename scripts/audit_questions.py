from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, str(Path(__file__).parent))
from generate_question_bank import call_llm, jaccard, tokens  # noqa: E402

LEVELS = ("basic", "intermediate", "advanced")

SYSTEM = """You are a strict senior engineer auditing an interview question bank for accuracy and quality.
Return ONLY a JSON object, no prose, no markdown fences:
{"verdict": "keep" | "fix" | "reject", "reason": "one sentence",
 "question": "improved question (only when verdict is fix)",
 "difficulty": "basic" | "intermediate" | "advanced",
 "key_points": [4-6 strings, for keep and fix]}

Verdict rules:
- reject if: the premise is wrong or misleading; the concept is about model TRAINING
  (overfitting, gradients, training time) instead of using models in RAG; it is the generic
  template "which metrics would you track and how would you interpret them" with no specific
  topic content; it duplicates or near-duplicates an EXISTING question; or it cannot be answered
  verbally in 2-4 minutes.
- fix if: the topic is good but the question is vague, circular, truly compound (asks 3 or more
  separate things), mislabeled in difficulty, or its key points are wrong, dated or generic.
  A question with one natural follow-on clause ("..., and why?", "..., and when would you avoid it?",
  "..., and how would you detect it?") is NOT compound: keep that wording. When you rewrite, keep the
  scenario, the trade-off and the "why/when not" part; make the question MORE specific, never shorter
  and more generic. If the question only needs better key points or a different difficulty, use "keep"
  with the corrected difficulty and key_points and do not change the wording.
- Fix any flawed premise instead of keeping it (for example, you always need both query and document
  embeddings, so "choose one under memory limits" makes no sense); if it cannot be repaired, reject.
- The "reason" must be specific to this question, never just "the question is compound".
- keep if: accurate, specific, one idea.

Difficulty: basic = definitions, when to use, simple comparison. intermediate = trade-offs,
parameter choices, diagnosing a specific symptom. advanced = production failures, scale, design decisions.

key_points rules: concrete, accurate statements a strong answer would make, naming the
mechanism (techniques, parameters, typical values, failure causes, how to verify it).
Follow current practice: use retrieval-tuned embedding models, never recommend Word2Vec, GloVe or
mBERT as an embedding choice for RAG, never treat TF-IDF as embeddings, define recall@k as the
fraction of relevant items found in the top k, and note that semantic chunking does not always beat
recursive splitting. No filler such as "improves user experience" or "explains the concept"."""


def load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def save(path: Path, rows: list[dict]) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(path)


def build_prompt(q: dict, existing: list[str]) -> str:
    ref = q.get("reference_answer", {})
    p = (
        f"Topic: {q['topic']} / {q['subtopic']}   Labeled difficulty: {q['difficulty']}\n"
        f"Question: {q['question']}\n"
        f"Concepts: {'; '.join(q['expected_concepts'])}\n"
        f"Current key points: {json.dumps(ref.get('key_points', []))}\n"
    )
    if existing:
        p += "\nEXISTING approved questions for this subtopic (reject duplicates of these):\n"
        p += "\n".join(f"- {e}" for e in existing[-30:]) + "\n"
    return p


def audit_one(q: dict, existing: list[str], model: str) -> dict | None:
    try:
        data = json.loads(call_llm(SYSTEM, build_prompt(q, existing), model, temperature=0.2))
    except Exception as exc:
        print(f"[warn] {q['id']} failed: {exc}")
        return None
    if data.get("verdict") not in ("keep", "fix", "reject"):
        print(f"[warn] {q['id']} gave no valid verdict")
        return None
    return data


def apply(q: dict, data: dict) -> str:
    verdict = data["verdict"]
    q["audit"] = {"verdict": verdict, "reason": str(data.get("reason", ""))}
    if verdict == "reject":
        q["review_status"] = "rejected"
        return "rejected"

    points = data.get("key_points")
    if not (isinstance(points, list) and len(points) >= 3):
        q["audit"]["note"] = "no usable key points returned; left pending"
        return "pending"

    if verdict == "fix" and str(data.get("question", "")).strip():
        q["original_question"] = q["question"]
        q["question"] = data["question"].strip()
    if data.get("difficulty") in LEVELS:
        q["difficulty"] = data["difficulty"]
    q.setdefault("reference_answer", {})["key_points"] = points
    q["review_status"] = "approved"
    return "fixed" if verdict == "fix" else "kept"


def write_report(path: Path, rows: list[dict], touched: set[str]) -> None:
    rejected = [r for r in rows if r["id"] in touched and r.get("review_status") == "rejected"]
    fixed = [r for r in rows if r["id"] in touched and r.get("original_question")]
    lines = ["# Audit report", "",
             f"Rejected: {len(rejected)}   Rewritten: {len(fixed)}   "
             f"Total approved now: {sum(r.get('review_status') == 'approved' for r in rows)}", "",
             "## Rejected (skim: restore any you disagree with)", ""]
    for r in rejected:
        lines.append(f"- **{r['subtopic']} / {r['difficulty']}** `{r['id']}`: {r['question']}")
        lines.append(f"  - why: {r['audit']['reason']}")
    lines += ["", "## Rewritten (check the new wording)", ""]
    for r in fixed:
        lines.append(f"- **{r['subtopic']} / {r['difficulty']}** `{r['id']}`")
        lines.append(f"  - was: {r['original_question']}")
        lines.append(f"  - now: {r['question']}")
        lines.append(f"  - why: {r['audit']['reason']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", type=Path, default=Path("data/question_bank.jsonl"))
    ap.add_argument("--model", default=os.getenv("QB_AUDIT_MODEL", "gpt-4o"),
                    help="use the strongest model your account has")
    ap.add_argument("--topic")
    ap.add_argument("--limit", type=int, help="audit only the first N pending questions")
    ap.add_argument("--report", type=Path, default=Path("data/audit_report.md"))
    args = ap.parse_args()

    rows = load(args.path)
    shutil.copyfile(args.path, args.path.with_suffix(args.path.suffix + ".bak"))
    todo = [r for r in rows if r.get("review_status") == "pending"
            and (not args.topic or r["topic"] == args.topic)]
    if args.limit:
        todo = todo[:args.limit]
    print(f"Auditing {len(todo)} pending question(s) with {args.model} "
          f"(backup: {args.path.name}.bak)")

    counts = {"kept": 0, "fixed": 0, "rejected": 0, "pending": 0}
    touched: set[str] = set()
    for i, q in enumerate(todo, 1):
        existing = [e["question"] for e in rows
                    if e is not q and e["subtopic"] == q["subtopic"]
                    and e.get("review_status") == "approved"]
        data = audit_one(q, existing, args.model)
        if data is None:
            counts["pending"] += 1
            continue
        new_text = str(data.get("question", "")).strip()
        if data["verdict"] == "fix" and new_text:
            nt = tokens(new_text)
            clash = next((e for e in existing if jaccard(nt, tokens(e)) >= 0.6), None)
            if clash:
                data = {"verdict": "reject",
                        "reason": f"rewrite duplicates an approved question: {clash[:90]}"}
        counts[apply(q, data)] += 1
        touched.add(q["id"])
        if i % 5 == 0:
            save(args.path, rows)
            print(f"  ...{i}/{len(todo)}")

    save(args.path, rows)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    write_report(args.report, rows, touched)
    print(f"Done. {counts}  Report: {args.report}")


if __name__ == "__main__":
    main()