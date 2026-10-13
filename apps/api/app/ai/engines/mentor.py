"""AI Mentor (daily plan note) and AI Career Guide."""

from app.ai import gateway
from app.ai.schemas import CareerOut, MentorOut

PROMPT_VERSION = "mentor-v1"


def mentor_task(name: str, progress: dict, plan: list[dict], stats: dict) -> gateway.Task:
    summary = {
        "course": progress.get("title"),
        "readiness": progress.get("readiness"),
        "weak": [w["title"] for w in progress.get("weak", [])][:5],
        "strong": [s["title"] for s in progress.get("strong", [])][:5],
        "plan": [p["title"] for p in plan],
        "stats": stats,
    }
    return gateway.Task(
        name="mentor.note",
        prompt_version=PROMPT_VERSION,
        tier="light",
        system="You are a supportive study mentor. In 3-4 sentences, explain today's priorities and why, using the data. Be honest about weak areas; no generic hype.",
        user=f"Learner: {name}\nData: {summary}",
        schema=MentorOut,
        offline=lambda: offline_mentor(name, summary),
        max_tokens=400,
    )


def offline_mentor(name: str, s: dict) -> dict:
    parts = [f"{name}, your readiness for {s['course']} is {round((s['readiness'] or 0) * 100)}%."]
    if s["weak"]:
        parts.append(f"Today, fix {', '.join(s['weak'][:2])} first: weak basics cost the most marks.")
    if s["plan"]:
        parts.append(f"Your plan has {len(s['plan'])} items; start with '{s['plan'][0]}'.")
    if s["stats"].get("accuracy"):
        parts.append(f"Recent accuracy is {round(s['stats']['accuracy'] * 100)}%.")
    return {"message": " ".join(parts), "focus": s["weak"][:3]}


def career_task(goal: str, education: str, mastery_summary: list[dict], catalog: list[dict]) -> gateway.Task:
    return gateway.Task(
        name="career.guide",
        prompt_version=PROMPT_VERSION,
        tier="standard",
        system=(
            "You are a practical career guide for learners in India and worldwide. Suggest 2-3 realistic paths for the "
            "learner's goal, why each fits, concrete next steps, and which platform courses (by slug, only from the given "
            "catalog) to take. Be honest about effort and timelines; do not promise jobs or salaries."
        ),
        user=f"Goal: {goal}\nEducation: {education}\nCurrent mastery: {mastery_summary}\nCatalog: {catalog}",
        schema=CareerOut,
        offline=lambda: offline_career(goal, catalog),
        max_tokens=1500,
    )


CAREER_KEYWORDS = {
    "competitive": ["government", "upsc", "ssc", "bank", "railway", "psc", "civil service", "officer", "group"],
    "technology": ["software", "developer", "programmer", "data", "ai", "machine learning", "web", "python", "coding", "it job"],
    "professional": ["ca", "chartered", "accountant", "finance", "audit", "tax", "cma", "commerce"],
    "language": ["english", "spoken", "communication", "abroad", "japan", "germany", "ielts", "interview"],
    "academic": ["class", "board", "neet", "jee", "engineering", "medical", "school"],
}


def offline_career(goal: str, catalog: list[dict]) -> dict:
    g = goal.lower()
    domains = [d for d, kws in CAREER_KEYWORDS.items() if any(k in g for k in kws)] or ["language", "technology"]
    paths = []
    for d in domains[:3]:
        courses = [c["slug"] for c in catalog if c["domain"] == d][:3]
        paths.append(
            {
                "title": {
                    "competitive": "Government job through competitive exams",
                    "technology": "Software & data career",
                    "professional": "Commerce & finance professional",
                    "language": "Communication skills for careers",
                    "academic": "Strong academic foundation",
                }[d],
                "why": f"Your goal mentions topics linked to {d} learning.",
                "next_steps": [
                    "Enroll in the first course below and follow the daily plan.",
                    "Take the diagnostic practice to find weak areas.",
                    "Review progress weekly on your dashboard.",
                ],
                "course_slugs": courses,
            }
        )
    return {"summary": f"Paths based on your goal: '{goal}'. Connect an AI provider for a personalised plan.", "paths": paths}
