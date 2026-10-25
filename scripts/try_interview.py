"""
Run a live interview in the terminal against your running API. A developer tool, not part of the product.

Place at: scripts/try_interview.py
Start the server first (uvicorn app.main:app --reload), then in another terminal:

    python scripts/try_interview.py
    python scripts/try_interview.py --questions 6 --difficulty advanced
    python scripts/try_interview.py --base http://127.0.0.1:8000 --prefix /api/v1

Each run registers a throwaway test user, so no login is needed. Type your answer, then press Enter on an
empty line to submit. Put INTERVIEW_DEBUG=1 in .env (local only) to also see WHY each question was chosen.
Needs httpx:  uv add --dev httpx
"""
from __future__ import annotations

import argparse
import json
import secrets
import sys

import httpx


def read_answer() -> str:
    print("\nYour answer (finish with an empty line, or type /quit):")
    lines = []
    while True:
        line = input("> ")
        if line.strip() == "/quit":
            sys.exit("Stopped.")
        if not line.strip():
            if lines:
                return "\n".join(lines)
            continue
        lines.append(line)


def show_question(q: dict) -> None:
    kind = " (follow-up)" if q.get("kind") == "follow_up" else ""
    print("\n" + "=" * 78)
    print(f"[{q.get('difficulty')}] {q.get('topic')} / {q.get('subtopic', '-')}{kind}")
    if q.get("lead_in"):
        print(f"Interviewer: {q['lead_in']}")
    print(f"Interviewer: {q['question']}")
    if q.get("selection"):
        sel = q["selection"]
        print(f"   [debug] intent={sel['intent']} target={sel['target_level']} scores={sel['chosen']}")
        print(f"   [debug] queries={sel['queries']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--prefix", default="/api/v1")
    ap.add_argument("--questions", type=int, default=5)
    ap.add_argument("--difficulty", default="intermediate", choices=["foundational", "intermediate", "advanced"])
    ap.add_argument("--static", action="store_true", help="use the old non-adaptive flow instead")
    args = ap.parse_args()

    http = httpx.Client(base_url=args.base + args.prefix, timeout=60)

    def call(method: str, path: str, **kw) -> dict:
        r = http.request(method, path, **kw)
        if r.status_code >= 400:
            sys.exit(f"{method} {path} -> {r.status_code}: {r.text[:400]}")
        return r.json()

    email = f"tester{secrets.token_hex(4)}@example.com"
    account = call("POST", "/auth/register", json={"name": "Test Candidate", "email": email, "password": "DemoPass123"})
    http.headers["Authorization"] = f"Bearer {account['access_token']}"

    created = call("POST", "/interview/create", json={
        "adaptive": not args.static, "question_count": args.questions, "difficulty": args.difficulty})
    print(f"Interview {created['id']}  adaptive={created['adaptive']}  questions={created['question_count']}")
    if not args.static and not created["adaptive"]:
        print("!! Adaptive was requested but is NOT active (bank unreachable or empty). "
              "Check MONGODB_URI, OPENAI_API_KEY and that ingestion ran. Continuing with the static flow.")
    iid = created["id"]

    question = call("POST", f"/interview/{iid}/start")["question"]
    while question:
        show_question(question)
        result = call("POST", f"/interview/{iid}/answer", json={"answer": read_answer()})
        ev = result["evaluation"]
        print(f"\n  score={ev['score']}/5  judge={ev.get('evaluator', 'keyword')}")
        print(f"  mentioned={ev.get('mentioned_concepts')}  covered={ev.get('covered_concepts')}  "
              f"missing={ev.get('missing_concepts')}")
        for pt in ev.get("points", []):            # only present when INTERVIEW_DEBUG=1
            mark = "[x]" if pt["covered"] else "[ ]"
            note = "  (rescued by re-check)" if pt.get("rescued") else ""
            print(f"   [judge] {mark} {pt['label']}  evidence={pt['evidence']!r}{note}")
        print(f"  feedback: {ev['feedback']}")
        question = result["next_question"]
        report = result["report"]

    print("\n" + "#" * 78 + "\nREPORT")
    print(f"score: {report['score']}/5")
    print("by area:", json.dumps(report.get("area_scores", {})))
    print("recommendations:", *report["recommendations"], sep="\n  - ")
    for item in report.get("review", []):
        print(f"\nReview ({item['score']}/5): {item['question']}")
        for p in item["key_points"]:
            print(f"   - {p}")


if __name__ == "__main__":
    main()