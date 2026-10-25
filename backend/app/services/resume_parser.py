import re
from collections import defaultdict

SKILL_ALIASES = {
    "python": "Python", "java": "Java", "javascript": "JavaScript", "typescript": "TypeScript",
    "c++": "C++", "c#": "C#", "golang": "Go", r"\bgo\b": "Go", "rust": "Rust",
    "sql": "SQL", "nosql": "NoSQL", "mongodb": "MongoDB", "postgresql": "PostgreSQL",
    "mysql": "MySQL", "redis": "Redis", "sqlite": "SQLite", "fastapi": "FastAPI",
    "django": "Django", "flask": "Flask", "spring boot": "Spring Boot", r"\.net": ".NET",
    r"react(?:\.js)?": "React", r"next\.js": "Next.js", r"node(?:\.js)?": "Node.js",
    "angular": "Angular", r"vue(?:\.js)?": "Vue.js", "html5?": "HTML", "css3?": "CSS",
    "machine learning": "Machine Learning", "deep learning": "Deep Learning",
    r"natural language processing|\bnlp\b": "NLP", "computer vision": "Computer Vision",
    r"\brag\b|retrieval augmented generation": "RAG", r"large language models?|\bllms?\b": "LLMs",
    "langchain": "LangChain", "langgraph": "LangGraph", "hugging ?face": "Hugging Face",
    "pytorch": "PyTorch", "tensorflow": "TensorFlow", "scikit.learn": "scikit-learn",
    "pandas": "pandas", "numpy": "NumPy", "faiss": "FAISS", "chromadb": "ChromaDB",
    "qdrant": "Qdrant", "pinecone": "Pinecone", "aws|amazon web services": "AWS",
    "azure": "Azure", r"\bgcp\b|google cloud": "GCP", "docker": "Docker",
    r"kubernetes|\bk8s\b": "Kubernetes", "terraform": "Terraform", "linux": "Linux",
    r"git(?:hub)?": "Git", "ci/cd": "CI/CD", r"\brest(?:ful)? apis?\b": "REST APIs",
    "graphql": "GraphQL", "microservices": "Microservices", "system design": "System Design",
    "data analysis": "Data Analysis", r"\bexcel\b": "Excel", "power bi": "Power BI",
    "tableau": "Tableau", "communication": "Communication", "leadership": "Leadership",
}

SECTION_NAMES = {
    "summary": {"summary", "professional summary", "profile", "objective", "career objective", "about me"},
    "skills": {"skills", "technical skills", "core skills", "skills and technologies", "technologies", "technical expertise"},
    "experience": {"experience", "work experience", "professional experience", "employment history", "work history", "career history"},
    "education": {"education", "academic background", "education and training"},
    "projects": {"projects", "personal projects", "academic projects", "selected projects"},
    "certifications": {"certifications", "certificates", "licenses and certifications"},
}
HEADING_MAP = {heading: section for section, headings in SECTION_NAMES.items() for heading in headings}


def _section_heading(line: str) -> str | None:
    cleaned = re.sub(r"^[\s#>*\u2022\-]+|[:\s]+$", "", line).lower()
    return HEADING_MAP.get(cleaned)


def _section_lines(lines: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = defaultdict(list)
    active: str | None = None
    for line in lines:
        heading = _section_heading(line)
        if heading:
            active = heading
        elif active and line.strip():
            sections[active].append(line.strip())
    return sections


def _unique_skills(text: str) -> list[str]:
    found: list[tuple[int, str]] = []
    lower = text.lower()
    for pattern, label in SKILL_ALIASES.items():
        for match in re.finditer(r"(?<![a-z0-9])(?:" + pattern + r")(?![a-z0-9])", lower, re.IGNORECASE):
            found.append((match.start(), label))
    result: list[str] = []
    for _, label in sorted(found):
        if label not in result:
            result.append(label)
    return result


def _clean_section(lines: list[str]) -> list[str]:
    return [re.sub(r"^[\s\u2022*\-\u2013]+", "", line).strip() for line in lines if line.strip()]


def extract_resume_profile(text: str) -> dict:
    """Extract contact details, recognized skills, and common resume sections."""
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    sections = _section_lines(lines)
    email_match = re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", text, re.IGNORECASE)
    phone_match = re.search(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)", text)
    linkedin_match = re.search(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w-]+/?", text, re.IGNORECASE)
    github_match = re.search(r"(?:https?://)?(?:www\.)?github\.com/[\w-]+/?", text, re.IGNORECASE)
    name = next((line for line in lines[:8] if len(line) <= 70 and not re.search(r"[@\d]|https?://|resume|curriculum vitae", line, re.IGNORECASE)
                 and len(line.split()) <= 5), None)
    skills = _unique_skills(text)
    # Keep uncatalogued items from an explicitly labeled skills section as well.
    for line in _clean_section(sections.get("skills", [])):
        for item in re.split(r"[,;|\u2022]+", line):
            item = re.sub(r"^[\s\u2022*\-]+", "", item).strip()
            if 1 < len(item) <= 50 and len(item.split()) <= 6 and item.lower() not in {s.lower() for s in skills}:
                skills.append(item)
    summary = " ".join(_clean_section(sections.get("summary", []))).strip() or None
    return {
        "name": name,
        "email": email_match.group(0) if email_match else None,
        "phone": phone_match.group(0).strip() if phone_match else None,
        "links": {
            "linkedin": linkedin_match.group(0) if linkedin_match else None,
            "github": github_match.group(0) if github_match else None,
        },
        "summary": summary,
        "skills": skills,
        "experience": _clean_section(sections.get("experience", [])),
        "education": _clean_section(sections.get("education", [])),
        "projects": _clean_section(sections.get("projects", [])),
        "certifications": _clean_section(sections.get("certifications", [])),
        "sections_found": sorted(sections),
        "extraction_warnings": (["Very little text was extracted; check the profile fields manually."] if len(text.strip()) < 40 else []),
    }
