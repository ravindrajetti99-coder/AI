"""AI Language Partner: conversation practice with gentle corrections."""

import re

from app.ai import gateway
from app.ai.schemas import LanguageReply

PROMPT_VERSION = "language-v1"
LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")


def chat_task(target_language: str, level: str, scenario: str, history: list[dict], message: str, helper_language: str = "en") -> gateway.Task:
    system = (
        f"You are a friendly conversation partner helping a learner practise {target_language} at CEFR level {level}. "
        f"Scenario: {scenario or 'everyday conversation'}. Reply naturally in {target_language} using vocabulary suitable "
        f"for {level}, keep replies to 1-3 sentences, and end with a question that keeps the conversation going. "
        "Separately, list corrections of the learner's last message (original, corrected, short explanation"
        f"{' in Telugu' if helper_language == 'te' else ''}), only for real errors. "
        "Add up to 3 useful vocabulary items with meanings, and a `next_prompt` the learner could try saying."
    )
    return gateway.Task(
        name="language.chat",
        prompt_version=PROMPT_VERSION,
        tier="standard",
        system=system,
        user=message[:2000],
        schema=LanguageReply,
        messages=history[-12:],
        offline=lambda: offline_reply(target_language, message, scenario),
        max_tokens=900,
    )


# Frequent errors made by Indian-language speakers learning English (rule set for offline mode).
ENGLISH_RULES = [
    (r"\bi am agree\b", "I agree", "'Agree' is already a verb; don't add 'am'."),
    (r"\bdiscuss about\b", "discuss", "'Discuss' takes a direct object: discuss the plan."),
    (r"\breturn back\b", "return", "'Return' already means 'go back'."),
    (r"\brevert back\b", "reply", "In Indian English 'revert' is often used for 'reply'; say 'reply' or 'get back to you'."),
    (r"\bmore better\b", "better", "'Better' is already comparative."),
    (r"\b(he|she|it) (go|do|have|want|like|come)\b", None, "Third person singular takes -s/-es: he goes, she does, it has."),
    (r"\ba ([aeiou]\w*)", None, "Use 'an' before a vowel sound: an apple, an hour."),
    (r"\bmyself is\b", "My name is", "Say 'My name is ...' or 'I am ...' to introduce yourself."),
    (r"\bwhat is your good name\b", "what is your name", "'Good name' is a literal translation; just say 'your name'."),
    (r"\bdo the needful\b", "please do what is needed", "'Do the needful' sounds dated outside India; say exactly what you need."),
    (r"\bi have been to (\w+) yesterday\b", None, "With a finished time like 'yesterday', use the past simple: I went to ... yesterday."),
    (r"\bsince (\d+) (years|months|days)\b", None, "Use 'for' with a length of time: for 2 years; 'since' with a starting point: since 2020."),
]
_THIRD = {"go": "goes", "do": "does", "have": "has", "want": "wants", "like": "likes", "come": "comes"}


def english_corrections(message: str) -> list[dict]:
    out = []
    for pattern, fix, why in ENGLISH_RULES:
        for m in re.finditer(pattern, message, flags=re.I):
            original = m.group(0)
            if fix is not None:
                corrected = fix
            elif pattern.startswith(r"\b(he|she|it)"):
                corrected = f"{m.group(1)} {_THIRD[m.group(2).lower()]}"
            elif pattern.startswith(r"\ba ("):
                corrected = f"an {m.group(1)}"
            elif "been to" in pattern:
                corrected = f"I went to {m.group(1)} yesterday"
            else:
                corrected = f"for {m.group(1)} {m.group(2)}"
            out.append({"original": original, "corrected": corrected, "explanation": why})
    if re.search(r"(^|[.!?]\s+)i\b", message):
        out.append({"original": "i", "corrected": "I", "explanation": "The pronoun 'I' is always a capital letter."})
    stripped = message.strip()
    if stripped and stripped[0].islower():
        out.append({"original": stripped.split()[0], "corrected": stripped.split()[0].capitalize(), "explanation": "Start a sentence with a capital letter."})
    return out


def offline_reply(target_language: str, message: str, scenario: str) -> dict:
    is_english = target_language.lower().startswith("english")
    corrections = english_corrections(message) if is_english else []
    if is_english:
        if "?" in message:
            reply = "Good question! Let me ask you one too: what do you usually do on weekends?"
        elif len(message.split()) < 5:
            reply = "Nice start. Can you tell me a little more, in two or three sentences?"
        else:
            reply = "That's interesting, thanks for sharing. Why do you feel that way?"
        nxt = "Try: 'In my free time I like to ... because ...'"
    else:
        reply = f"(Offline mode) Keep practising {target_language}: write a short sentence about your day."
        nxt = ""
    return {"reply": reply, "corrections": corrections, "vocabulary": [], "next_prompt": nxt}
