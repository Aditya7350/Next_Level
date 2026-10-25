from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, str(Path(__file__).parent))
from generate_question_bank import call_llm  # noqa: E402

SYSTEM = """You are a senior engineer writing an interviewer's answer key.
Return ONLY a JSON object, no prose, no markdown fences, in one of two shapes.

Normal:
{"key_points": [3-6 strings], "common_mistakes": [2-3 strings], "follow_up_questions": [2-3 strings]}

If the question has a wrong premise, mixes unrelated concepts, is unanswerable as asked,
or is technically misleading, return instead:
{"flawed": true, "reason": "<one sentence>"}

Rules for key_points: each is a CONCRETE statement a strong answer would make, with specifics
(named techniques, parameters, typical value ranges, tools, causes, fixes). Never write
generic items such as "explains the concept" or "mentions trade-offs". Be accurate per
current industry practice. follow_up_questions must be specific and short (one sentence)."""


def load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def save(path: Path, rows: list[dict]) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(path)


def build_prompt(q: dict) -> str:
    return (
        f"Topic: {q['topic']} / {q['subtopic']}  (difficulty: {q['difficulty']})\n"
        f"Question: {q['question']}\n"
        f"Concepts this question is meant to test: {', '.join(q['expected_concepts'])}\n"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", type=Path, default=Path("data/question_bank.jsonl"))
    ap.add_argument("--model", default=os.getenv("QB_MODEL", "gpt-4o-mini"))
    args = ap.parse_args()

    rows = load(args.path)
    todo = [r for r in rows if not r.get("reference_answer") and not r.get("flag")]
    print(f"{len(todo)} of {len(rows)} questions need an answer key.")

    done = flagged = failed = 0
    for i, q in enumerate(todo, 1):
        try:
            data = json.loads(call_llm(SYSTEM, build_prompt(q), args.model, temperature=0.2))
        except Exception as exc:
            print(f"[warn] {q['id']} failed: {exc}")
            failed += 1
            continue

        if data.get("flawed"):
            q["flag"] = str(data.get("reason", "flagged as flawed"))
            flagged += 1
        elif isinstance(data.get("key_points"), list) and len(data["key_points"]) >= 3:
            q["reference_answer"] = {
                "key_points": data["key_points"],
                "common_mistakes": data.get("common_mistakes", []),
            }
            if data.get("follow_up_questions"):
                q["follow_up_questions"] = data["follow_up_questions"]
            done += 1
        else:
            print(f"[warn] {q['id']} returned unusable output")
            failed += 1

        if i % 10 == 0:
            save(args.path, rows)
            print(f"  ...{i}/{len(todo)}")

    save(args.path, rows)
    print(f"Done. answered={done} flagged={flagged} failed={failed} -> {args.path}")


if __name__ == "__main__":
    main()