"""
Tiny helper to fix individual questions by id (ids appear in audit_report.md).

Place at: scripts/set_status.py
Usage:
  python scripts/set_status.py rejected q_id1 q_id2 ...      # reject these
  python scripts/set_status.py approved q_id1 ...            # restore / approve these
  python scripts/set_status.py edit q_id "New question text" # change the wording
Options: --path data/question_bank.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["rejected", "approved", "pending", "edit"])
    ap.add_argument("values", nargs="+")
    ap.add_argument("--path", type=Path, default=Path("data/question_bank.jsonl"))
    args = ap.parse_args()

    with args.path.open(encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    by_id = {r["id"]: r for r in rows}

    if args.action == "edit":
        if len(args.values) != 2:
            sys.exit('edit needs exactly: <id> "<new question text>"')
        qid, text = args.values
        if qid not in by_id:
            sys.exit(f"unknown id {qid}")
        by_id[qid].setdefault("original_question", by_id[qid]["question"])
        by_id[qid]["question"] = text.strip()
        print(f"edited {qid}")
    else:
        for qid in args.values:
            if qid not in by_id:
                print(f"[skip] unknown id {qid}")
                continue
            by_id[qid]["review_status"] = args.action
            print(f"{qid} -> {args.action}")

    tmp = args.path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(args.path)


if __name__ == "__main__":
    main()