"""Seed courses. Each module defines EXAM, COURSE (with its tree) and CONCEPTS.

Order matters only for readability: the loader upserts every concept before any tree,
so a course may reuse a concept owned by another (interview skills reuses the spoken
English self-introduction, and mastery earned in one course counts in the other)."""

from app.seed.courses import ca_depreciation, interview_skills, physics_electricity, python_basics, spoken_english, ssc_quant

ALL_COURSES = [ssc_quant, physics_electricity, ca_depreciation, python_basics, spoken_english, interview_skills]
