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
# Fixed phrases only; articles and third-person verbs need context and are handled below.
ENGLISH_RULES = [
    (r"\bi am agree\b", "I agree", "'Agree' is already a verb; don't add 'am'."),
    (r"\bdiscuss about\b", "discuss", "'Discuss' takes a direct object: discuss the plan."),
    (r"\breturn back\b", "return", "'Return' already means 'go back'."),
    (r"\brevert back\b", "reply", "In Indian English 'revert' is often used for 'reply'; say 'reply' or 'get back to you'."),
    (r"\bmore better\b", "better", "'Better' is already comparative."),
    (r"\bmyself is\b", "My name is", "Say 'My name is ...' or 'I am ...' to introduce yourself."),
    (r"\bwhat is your good name\b", "what is your name", "'Good name' is a literal translation; just say 'your name'."),
    (r"\bdo the needful\b", "please do what is needed", "'Do the needful' sounds dated outside India; say exactly what you need."),
    (r"\bi have been to (\w+) yesterday\b", "I went to {0} yesterday", "With a finished time like 'yesterday', use the past simple: I went to ... yesterday."),
    (r"\bsince (\d+) (years|months|days)\b", "for {0} {1}", "Use 'for' with a length of time: for 2 years; 'since' with a starting point: since 2020."),
]
_THIRD = {"go": "goes", "do": "does", "have": "has", "want": "wants", "like": "likes", "come": "comes"}
_THIRD_PERSON = re.compile(r"\b(he|she|it) (go|do|have|want|like|come)\b", re.I)
# After these words the bare verb is right: "did he go", "will it come", "let her go", "saw it go".
_BARE_VERB_CONTEXT = re.compile(
    r"\b(do|does|did|will|would|can|could|shall|should|may|might|must|don't|doesn't|didn't|won't|wouldn't|can't|cannot|couldn't|shouldn't|"
    r"let|lets|make|makes|made|help|helps|helped|see|sees|saw|watch|watched|hear|heard|why not)\s+$",
    re.I,
)
_VOWEL_SOUND_START = re.compile(r"^(hour|honest|honou?r|heir)", re.I)  # silent h
_CONSONANT_SOUND_START = re.compile(r"^(uni|use|usu|uti|ure|uro|ufo|u-|eu|ewe|one\b|one-|once)", re.I)  # "you"/"wuh" sounds
_VOWEL_LETTER_NAMES = set("AEFHILMNORSX")  # an MBA, an FIR, an SSC exam; a UPSC exam


def _vowel_sound(word: str) -> bool:
    if len(word) > 1 and word.isupper():  # abbreviations are read letter by letter
        return word[0] in _VOWEL_LETTER_NAMES
    if _VOWEL_SOUND_START.match(word):
        return True
    if _CONSONANT_SOUND_START.match(word):
        return False
    return word[0].lower() in "aeiou"


def _article_fixes(message: str) -> list[dict]:
    out = []
    for m in re.finditer(r"(^|[.!?]\s+|\s)(a|an|A|An)\s+([A-Za-z][\w'-]*)", message):
        lead, article, word = m.groups()
        sentence_start = lead == "" or lead.strip() in (".", "!", "?")
        if article[0] == "A" and not sentence_start:
            continue  # "Plan A is", "grade A in maths": a label, not an article
        wanted = "an" if _vowel_sound(word) else "a"
        if article.lower() == wanted:
            continue
        fixed = wanted.capitalize() if article[0] == "A" else wanted
        why = (
            "Use 'an' before a vowel sound: an apple, an hour, an MBA."
            if wanted == "an"
            else "Use 'a' before a consonant sound: a university, a European, a one-rupee coin."
        )
        out.append({"original": f"{article} {word}", "corrected": f"{fixed} {word}", "explanation": why})
    return out


def english_corrections(message: str) -> list[dict]:
    out = []
    for pattern, fix, why in ENGLISH_RULES:
        for m in re.finditer(pattern, message, flags=re.I):
            out.append({"original": m.group(0), "corrected": fix.format(*m.groups()), "explanation": why})
    for m in _THIRD_PERSON.finditer(message):
        if _BARE_VERB_CONTEXT.search(message[: m.start()]):
            continue
        out.append(
            {
                "original": m.group(0),
                "corrected": f"{m.group(1)} {_THIRD[m.group(2).lower()]}",
                "explanation": "Third person singular takes -s/-es: he goes, she does, it has.",
            }
        )
    out += _article_fixes(message)
    if re.search(r"(?<![\w.'])i(?![\w])(?!\.[a-z])", message):
        out.append({"original": "i", "corrected": "I", "explanation": "The pronoun 'I' is always a capital letter."})
    first = message.strip().split()[0] if message.strip() else ""
    if first and first[0].islower() and first != "i":
        out.append({"original": first, "corrected": first[0].upper() + first[1:], "explanation": "Start a sentence with a capital letter."})
    seen, unique = set(), []
    for c in out:
        key = (c["original"].lower(), c["corrected"])
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


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
