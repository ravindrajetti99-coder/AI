"""Small text utilities shared by retrieval and the offline engines (no external NLP deps)."""

import re
from collections import Counter

STOPWORDS = set(
    """a an the and or but if then else of to in on at by for with from as is are was were be been being this that
    these those it its it's into over under than so such not no can could should would will shall may might must do
    does did done have has had having you your we our they their he she his her them i me my what which who whom
    whose when where why how all any both each few more most other some own same very just also only about above
    after again against below between during before further once here there out up down off too s t""".split()
)

_WORD = re.compile(r"[a-zA-Zऀ-ൿ][\w'\-ऀ-ൿ]*")
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(ऀ-ൿ])")


def tokenize(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text or "")]


def content_terms(text: str) -> list[str]:
    return [w for w in tokenize(text) if w not in STOPWORDS and len(w) > 1]


def term_counts(text: str) -> dict[str, int]:
    return dict(Counter(content_terms(text)))


def sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    return [s.strip() for s in _SENT.split(text) if len(s.strip()) > 2]


def extractive_summary(text: str, max_sentences: int = 5) -> list[str]:
    """Rank sentences by the frequency of their content words; keep original order."""
    sents = sentences(text)
    if len(sents) <= max_sentences:
        return sents
    freq = Counter(content_terms(text))
    top = max(freq.values()) if freq else 1

    def score(s: str) -> float:
        terms = content_terms(s)
        if not terms:
            return 0.0
        return sum(freq[t] / top for t in terms) / (len(terms) ** 0.5)

    ranked = sorted(range(len(sents)), key=lambda i: score(sents[i]), reverse=True)[:max_sentences]
    return [sents[i] for i in sorted(ranked)]


def coverage(expected: str, answer_terms: set[str]) -> float:
    """Share of an expected point's content words that appear in the answer (with light stemming)."""
    exp = {_stem(t) for t in content_terms(expected)}
    if not exp:
        return 0.0
    got = {_stem(t) for t in answer_terms}
    return len(exp & got) / len(exp)


def _stem(word: str) -> str:
    for suf in ("ations", "ation", "ingly", "ing", "edly", "ed", "ies", "es", "s", "ly"):
        if len(word) > len(suf) + 3 and word.endswith(suf):
            return word[: -len(suf)]
    return word


def stems(text: str) -> set[str]:
    return {_stem(t) for t in content_terms(text)}
