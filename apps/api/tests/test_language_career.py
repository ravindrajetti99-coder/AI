"""Offline language partner corrections, the language chat endpoint, career guide and mentor."""

import pytest
from conftest import API

from app.ai.engines import language, mentor


def fixes(text: str) -> dict[str, str]:
    return {c["original"].lower(): c["corrected"] for c in language.english_corrections(text)}


@pytest.mark.parametrize(
    ("text", "original", "corrected"),
    [
        ("I am agree with you.", "i am agree", "I agree"),
        ("We will discuss about the plan.", "discuss about", "discuss"),
        ("He go to college daily.", "he go", "He goes"),
        ("She have two brothers.", "she have", "She has"),
        ("I ate a apple.", "a apple", "an apple"),
        ("We waited a hour.", "a hour", "an hour"),
        ("He studies at an university.", "an university", "a university"),
        ("I have been to Chennai yesterday.", "i have been to chennai yesterday", "I went to Chennai yesterday"),
        ("I am working here since 3 years.", "since 3 years", "for 3 years"),
        ("What is your good name?", "what is your good name", "what is your name"),
        ("Myself is Ravi.", "myself is", "My name is"),
    ],
)
def test_common_errors_are_corrected(text, original, corrected):
    assert fixes(text).get(original) == corrected


@pytest.mark.parametrize(
    "text",
    [
        "I study at a university in Pune.",
        "Did he go to the market?",
        "Does she have a pen?",
        "Will it come back?",
        "It is an honest mistake.",
        "She bought a one-rupee coin and a European car.",
        "I agree with you.",
    ],
)
def test_correct_sentences_are_left_alone(text):
    assert language.english_corrections(text) == []


def test_lowercase_i_and_capitals_are_reported_once():
    found = language.english_corrections("yesterday i went home and i slept.")
    assert [(c["original"], c["corrected"]) for c in found].count(("i", "I")) == 1
    assert ("yesterday", "Yesterday") in [(c["original"], c["corrected"]) for c in found]


def test_language_chat_offline_keeps_the_conversation(learner):
    first = learner.post(f"{API}/language/chat", json={"message": "i am agree that cricket is fun", "level": "A2", "scenario": "chatting with a friend"})
    assert first.status_code == 200
    body = first.json()
    assert body["provider"] == "offline" and body["reply"]
    assert {"original": "i am agree", "corrected": "I agree"}.items() <= body["corrections"][0].items()
    second = learner.post(f"{API}/language/chat", json={"message": "What do you like?", "conversation_id": body["conversation_id"]}).json()
    assert second["conversation_id"] == body["conversation_id"]
    assert learner.post(f"{API}/language/chat", json={"message": "hi", "level": "Z9"}).status_code == 422


@pytest.mark.parametrize(
    ("goal", "domain"),
    [
        ("I want a government job through SSC", "competitive"),
        ("I want to become a chartered accountant", "professional"),
        ("I want a software developer job", "technology"),
        ("Crack my first job interview after college", "career"),
        ("Build a career in data science", "technology"),
        ("I want a railway job", "competitive"),
    ],
)
def test_offline_career_paths_match_the_goal(goal, domain):
    catalog = [
        {"slug": "ssc-cgl-quant-arithmetic", "title": "SSC", "domain": "competitive"},
        {"slug": "ca-foundation-depreciation", "title": "CA", "domain": "professional"},
        {"slug": "python-fundamentals", "title": "Python", "domain": "technology"},
        {"slug": "job-interview-skills", "title": "Interview", "domain": "career"},
        {"slug": "spoken-english-telugu", "title": "English", "domain": "language"},
    ]
    paths = mentor.offline_career(goal, catalog)["paths"]
    assert paths[0]["course_slugs"] == [next(c["slug"] for c in catalog if c["domain"] == domain)]
    assert len(paths) == 1, [p["title"] for p in paths]  # short keywords like "ca"/"ai" must not match inside words


def test_career_guide_endpoint(learner):
    assert learner.post(f"{API}/career/guide", json={}).status_code == 400
    r = learner.post(f"{API}/career/guide", json={"goal": "I want to become a python developer"}).json()
    assert r["provider"] == "offline" and r["paths"][0]["course_slugs"] == ["python-fundamentals"]
    # The goal is saved, so the next call can omit it.
    assert learner.post(f"{API}/career/guide", json={}).status_code == 200
