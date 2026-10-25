"""Resume-grounded interview question generation for the local MVP."""

type Question = tuple[str, str, str, list[str]]


def _clean_fact(value: object, limit: int = 180) -> str | None:
    if not isinstance(value, str):
        return None
    fact = " ".join(value.split()).strip(" \"'“”")
    if not fact:
        return None
    if len(fact) > limit:
        fact = fact[: limit - 1].rsplit(" ", 1)[0] + "…"
    return fact


def _items(value: object, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        fact = _clean_fact(item)
        if fact and fact.casefold() not in {existing.casefold() for existing in result}:
            result.append(fact)
        if len(result) == limit:
            break
    return result


def generate_resume_questions(
    resume: dict,
    role: str,
    difficulty: str,
    question_count: int = 20,
) -> list[Question]:
    """Build interview prompts from the resume parser's extracted profile fields."""
    profile = resume.get("profile", {})
    if not isinstance(profile, dict):
        return []

    role_focus = _clean_fact(role, 40) or "this role"
    questions: list[Question] = []

    for project in _items(profile.get("projects"), 2):
        questions.append((
            f'Your resume mentions "{project}". What problem were you solving, what part did you own, and which trade-off mattered most?',
            "Resume project",
            difficulty,
            ["problem", "ownership", "tradeoffs"],
        ))

    for experience in _items(profile.get("experience"), 1):
        questions.append((
            f'In the experience you describe as "{experience}", what challenge took the most judgment, and what did you learn?',
            "Experience",
            difficulty,
            ["challenge", "judgment", "learning"],
        ))

    for skill in _items(profile.get("skills"), 4):
        questions.append((
            f"Your resume lists {skill}. Where have you applied it for {role_focus}, and what changed as a result?",
            skill,
            difficulty,
            [skill.casefold(), "application", "impact"],
        ))
        questions.append((
            f"How did you validate your use of {skill}, and what would you improve next time?",
            skill,
            difficulty,
            [skill.casefold(), "validation", "improvement"],
        ))

    summary = _clean_fact(profile.get("summary"))
    if summary:
        questions.append((
            f'Your resume summary highlights "{summary}". What evidence best demonstrates that impact?',
            "Resume summary",
            difficulty,
            ["evidence", "impact", "result"],
        ))

    resume_facts = (
        _items(profile.get("projects"), 2)
        + _items(profile.get("experience"), 1)
        + _items(profile.get("skills"), 4)
        + ([summary] if summary else [])
    )
    follow_ups = [
        ("What would you improve next time, and why?", ["improvement", "reasoning"]),
        ("How did you measure whether it was successful?", ["measurement", "impact"]),
        ("What was the hardest decision you made?", ["decision", "tradeoffs"]),
        ("How would you adapt this experience to {role}?", ["adaptation", "role fit"]),
        ("What did you learn that changed how you work?", ["learning", "reflection"]),
        ("How would you explain its value to a nontechnical teammate?", ["communication", "impact"]),
        ("What risks or edge cases did you have to account for?", ["risk", "judgment"]),
        ("What would you do differently with more time?", ["prioritization", "improvement"]),
    ]
    for index, (follow_up, concepts) in enumerate(follow_ups):
        if len(questions) >= question_count:
            break
        if not resume_facts:
            break
        fact = resume_facts[index % len(resume_facts)]
        prompt = follow_up.format(role=role_focus)
        questions.append((
            f'Considering "{fact}": {prompt}',
            "Resume follow-up",
            difficulty,
            concepts,
        ))

    return questions[:question_count]
