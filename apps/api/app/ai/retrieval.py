"""Retrieval over uploaded source material (BM25 ranking on pre-computed term counts).

BM25 runs anywhere (SQLite or PostgreSQL) with no embedding model. When the corpus grows,
replace `search` with a pgvector + full-text hybrid; callers only depend on its output shape.
"""

import math
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.text import content_terms, term_counts
from app.modules.ingest.models import Chunk, SourceDocument

K1, B = 1.5, 0.75
_PAGE = re.compile(r"^\f?\[page (\d+)\]")
_HEADING = re.compile(r"^\s{0,3}(#{1,6}\s+.+|[A-Z][A-Za-z0-9 ,:&()\-]{2,80})\s*$")


def chunk_text(text: str, target_words: int = 350, overlap_words: int = 40) -> list[dict]:
    """Heading-aware chunking: split on blank lines, keep the latest heading, pack paragraphs
    up to ~target_words, and overlap a little so facts on a boundary are not lost."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    chunks: list[dict] = []
    heading = ""
    buf: list[str] = []
    words = 0
    fresh = 0  # words added since the last flush (the overlap tail alone is not worth a chunk)
    page = 1

    def flush():
        nonlocal buf, words, fresh
        if buf and fresh:
            body = "\n\n".join(buf)
            chunks.append({"heading": heading, "text": body, "page": page})
            tail = body.split()[-overlap_words:] if overlap_words else []
            buf = [" ".join(tail)] if tail else []
            words, fresh = len(tail), 0

    for p in paragraphs:
        marker = _PAGE.match(p)  # extract_text() starts each PDF page with "\f[page N]"
        if marker:
            flush()
            page = int(marker.group(1))
            p = p[marker.end() :].strip()
            if not p:
                continue
        first_line = p.splitlines()[0]
        if len(p.split()) <= 12 and _HEADING.match(first_line) and len(p.splitlines()) == 1:
            flush()
            buf, words, fresh = [], 0, 0
            heading = first_line.lstrip("# ").strip()
            continue
        n = len(p.split())
        if words + n > target_words and fresh:
            flush()
        buf.append(p)
        words += n
        fresh += n
    flush()
    return chunks


def store_chunks(db: Session, document: SourceDocument, text: str) -> int:
    pieces = chunk_text(text)
    for i, piece in enumerate(pieces):
        db.add(
            Chunk(
                document_id=document.id,
                course_id=document.course_id,
                ordinal=i,
                page=piece["page"],
                heading=piece["heading"][:300],
                text=piece["text"],
                tokens=int(len(piece["text"].split()) * 1.3),
                terms=term_counts(piece["heading"] + " " + piece["text"]),
            )
        )
    return len(pieces)


def search(db: Session, query: str, course_id: uuid.UUID | None = None, k: int = 5, document_id: uuid.UUID | None = None) -> list[dict]:
    q_terms = content_terms(query)
    if not q_terms:
        return []
    stmt = select(Chunk, SourceDocument.title).join(SourceDocument, SourceDocument.id == Chunk.document_id)
    if document_id:
        stmt = stmt.where(Chunk.document_id == document_id)
    elif course_id:
        stmt = stmt.where(Chunk.course_id == course_id)
    rows = db.execute(stmt).all()
    if not rows:
        return []
    n = len(rows)
    avgdl = sum(sum(c.terms.values()) for c, _ in rows) / n or 1.0
    df: dict[str, int] = {}
    for c, _ in rows:
        for t in set(q_terms):
            if t in c.terms:
                df[t] = df.get(t, 0) + 1
    scored = []
    for c, title in rows:
        dl = sum(c.terms.values()) or 1
        score = 0.0
        for t in q_terms:
            tf = c.terms.get(t, 0)
            if not tf:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            score += idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * dl / avgdl))
        if score > 0:
            scored.append((score, c, title))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {"id": str(c.id), "document_id": str(c.document_id), "title": title, "heading": c.heading, "page": c.page, "text": c.text, "score": round(s, 3)}
        for s, c, title in scored[:k]
    ]
