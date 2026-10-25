"""
Step 3: review questions in the terminal.

Place at: scripts/review_questions.py
Run:      python scripts/review_questions.py --path data/question_bank.jsonl
Options:  --topic RAG   --subtopic chunking   --only-flagged   --status pending

Keys:  a approve | r reject | e edit question | k rewrite key points | d change difficulty | s skip | q quit
Progress is saved after every decision, so you can quit any time.
"""
from __future__ import annotations

import argparse
import json
import re
import textwrap
from pathlib import Path


def load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def save(path: Path, rows: list[dict]) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(path)


def auto_flags(q: dict) -> list[str]:
    text = q["question"]
    out = []
    if q.get("flag"):
        out.append(f"LLM says flawed: {q['flag']}")
    if text.count("?") > 1:
        out.append("multiple questions ('?' appears more than once)")
    if len(text.split()) > 40:
        out.append(f"long ({len(text.split())} words)")
    if len(re.findall(r"\b(what|how|which|why)\b", text.lower())) >= 3:
        out.append("compound (3+ question words, probably several questions in one)")
    if not q.get("reference_answer"):
        out.append("no reference answer yet")
    return out


def show(q: dict, pos: int, total: int) -> None:
    print("\n" + "=" * 78)
    print(f"[{pos}/{total}] {q['topic']} / {q['subtopic']}  |  {q['difficulty']}  |  {q['id']}")
    print("=" * 78)
    print(textwrap.fill(q["question"], 78))
    print("\nExpected concepts: " + "; ".join(q["expected_concepts"]))
    ref = q.get("reference_answer")
    if ref:
        print("\nKey points:")
        for p in ref["key_points"]:
            print(textwrap.fill(f"- {p}", 78, subsequent_indent="  "))
        if ref.get("common_mistakes"):
            print("Common mistakes:")
            for p in ref["common_mistakes"]:
                print(textwrap.fill(f"- {p}", 78, subsequent_indent="  "))
    flags = auto_flags(q)
    if flags:
        print("\n!! " + "\n!! ".join(flags))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", type=Path, default=Path("data/question_bank.jsonl"))
    ap.add_argument("--topic")
    ap.add_argument("--subtopic")
    ap.add_argument("--status", default="pending")
    ap.add_argument("--only-flagged", action="store_true")
    args = ap.parse_args()

    rows = load(args.path)
    queue = [
        r for r in rows
        if r.get("review_status") == args.status
        and (not args.topic or r["topic"] == args.topic)
        and (not args.subtopic or r["subtopic"] == args.subtopic)
        and (not args.only_flagged or auto_flags(r))
    ]
    print(f"{len(queue)} question(s) to review.")

    for pos, q in enumerate(queue, 1):
        while True:
            show(q, pos, len(queue))
            key = input("\n[a]pprove [r]eject [e]dit-question [k]ey-points [d]ifficulty [s]kip [q]uit > ").strip().lower()
            if key == "a":
                q["review_status"] = "approved"
            elif key == "r":
                q["review_status"] = "rejected"
            elif key == "e":
                new = input("New question text (blank = keep): ").strip()
                if new:
                    q["question"] = new
                    q.pop("flag", None)
                continue  # show again after editing
            elif key == "d":
                new = input("Difficulty (basic/intermediate/advanced): ").strip().lower()
                if new in ("basic", "intermediate", "advanced"):
                    q["difficulty"] = new
                continue
            elif key == "k":
                print("Type new key points, one per line. Empty line to finish "
                      "(empty first line keeps the existing ones).")
                pts = []
                while True:
                    line = input("> ").strip()
                    if not line:
                        break
                    pts.append(line)
                if pts:
                    q.setdefault("reference_answer", {})["key_points"] = pts
                continue
            elif key == "s":
                break
            elif key == "q":
                save(args.path, rows)
                print("Saved. Bye.")
                return
            else:
                continue
            save(args.path, rows)
            break

    save(args.path, rows)
    approved = sum(r["review_status"] == "approved" for r in rows)
    print(f"\nDone. approved={approved} total={len(rows)}")


if __name__ == "__main__":
    main()