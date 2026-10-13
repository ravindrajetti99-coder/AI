// Shapes returned by the EduVerse API (see apps/api/app/modules/*/router.py).

export type Role = "learner" | "reviewer" | "admin";

export type User = { id: string; email: string; name: string; role: Role; preferred_locale: string };

export type Profile = {
  target_exams: string[];
  exam_date: string | null;
  daily_minutes_goal: number;
  education_level: string;
  languages: string[];
  career_goal: string;
};

export type Me = User & { profile: Profile };

export type TokenOut = { access_token: string; refresh_token: string; expires_in: number; user: User };

export type Domain = { code: string; name: string; course_count: number };

export type Course = {
  id: string;
  slug: string;
  title: string;
  description: string;
  domain: string;
  level: string;
  locales: string[];
  status: string;
  color: string;
  concept_count: number;
  question_count: number;
};

export type ConceptBrief = { id: string; slug: string; title: string; weight: number };

export type TreeNode = { id: string; node_type: string; title: string; position: number; concepts: ConceptBrief[]; children: TreeNode[] };

export type ExamProfile = { id: string; slug: string; name: string; body: string; domain: string; pattern: Record<string, unknown> };

export type CourseDetail = Course & { exam_profile: ExamProfile | null; tree: TreeNode[] };

export type ConceptDetail = {
  id: string;
  slug: string;
  title: string;
  summary: string;
  domain: string;
  prerequisites: ConceptBrief[];
  unlocks: ConceptBrief[];
  lesson_levels: Record<string, number[]>;
  flashcard_count: number;
  question_count: number;
  courses: { slug: string; title: string }[];
};

export type LessonBody = {
  definition: string;
  explanation: string;
  examples: { title: string; body: string }[];
  diagram: string;
  key_points: string[];
  common_mistakes: string[];
  memory_technique: string;
  exam_relevance: string;
  check_questions: { question: string; answer: string }[];
  citations: string[];
};

export type Lesson = {
  id: string | null;
  concept_id: string;
  level: number;
  locale: string;
  body: LessonBody | null;
  status: string;
  source?: string;
  verified?: boolean;
  note?: string;
  can_generate?: boolean;
};

export type Option = { id: string; text: string };

export type QType = "mcq" | "multi" | "assertion_reason" | "case_study" | "numerical" | "descriptive" | "interview" | "coding" | "speaking";

export type Question = {
  id: string;
  qtype: QType;
  stem: string;
  payload: {
    options?: Option[];
    passage?: string;
    assertion?: string;
    reason?: string;
    unit?: string;
    max_marks?: number;
    word_limit?: number;
    language?: string;
    function_name?: string;
    starter_code?: string;
    examples?: { args: unknown[]; expected: unknown }[];
    sentence?: string;
    translation?: string;
    select_count_hint?: string;
  };
  difficulty: string;
  source: string;
  pyq_year: number | null;
  concepts: { id: string; slug: string; title: string }[];
};

export type Step = { step: number; kind: string; body: string };

export type MasteryChange = { concept_id: string; before: number; after: number; label: string };

export type CodeRun = {
  ok: boolean;
  passed: number;
  total: number;
  results: { args?: unknown[]; expected?: unknown; got?: unknown; passed: boolean; error?: string; hidden?: boolean }[];
  error: string;
  stdout: string;
  timed_out: boolean;
};

export type Evaluation = {
  criteria: { criterion: string; max_marks: number; awarded: number; comment: string }[];
  total: number;
  max_total: number;
  missing_points: string[];
  strengths: string[];
  improvements: string[];
  presentation_feedback: string;
  model_answer: string;
};

export type CodeReview = {
  score: number;
  summary: string;
  findings: { category: string; severity: "info" | "warning" | "error"; line: number | null; message: string; suggestion: string }[];
};

export type Feedback = {
  answered?: boolean;
  correct_answer?: unknown;
  explanation?: string;
  mistake_note?: string;
  unit?: string;
  partial?: boolean;
  // speaking
  accuracy?: number;
  missed?: string[];
  substitutions?: { expected: string; heard: string }[];
  target?: string;
  // coding
  run?: CodeRun;
  review?: CodeReview;
  review_source?: string;
  // descriptive / interview
  evaluation?: Evaluation;
  evaluated_by?: string;
  note?: string;
};

export type AttemptResult = {
  attempt_id: string;
  score: number;
  is_correct: boolean;
  correct_answer: unknown;
  explanation: string;
  feedback: Feedback;
  steps: Step[];
  mastery: MasteryChange[];
  hints_used: number;
};

export type NextQuestion = {
  question: Question | null;
  concept: { id: string; slug?: string; title: string; mastery?: number; label?: string };
  reason: string;
};

export type ConceptProgress = { concept_id: string; slug: string; title: string; weight: number; mastery: number; attempts: number; label: string };

export type CourseProgress = {
  course_id: string;
  slug: string;
  title: string;
  domain: string;
  readiness: number;
  coverage: number;
  concepts: ConceptProgress[];
  weak: ConceptProgress[];
  strong: ConceptProgress[];
  modules: { node_id: string; title: string; mastery: number; concepts: number }[];
};

export type PlanItem = {
  id: string;
  course_id: string;
  kind: "review" | "learn" | "practice" | "weak" | "test";
  concept_id: string | null;
  title: string;
  reason: string;
  minutes: number;
  status: "todo" | "done" | "skipped";
  date: string;
};

export type ReviewRow = {
  id: string;
  concept: { id: string; slug: string; title: string };
  stage: number;
  stage_name: string;
  stage_day: number;
  due_at: string;
  last_result: string;
};

export type Stats = {
  attempts: number;
  accuracy: number;
  practice_minutes: number;
  lesson_minutes: number;
  active_days: number;
  streak_days: number;
  avg_seconds_per_question: number;
};

export type Dashboard = {
  user: { name: string; role: Role };
  courses: CourseProgress[];
  stats: Stats;
  due_reviews: ReviewRow[];
  upcoming_reviews: ReviewRow[];
  plan: PlanItem[];
  ai: { providers: string[]; mode: "live" | "offline" };
};

export type TestSummary = { id: string; slug: string; title: string; kind: string; duration_minutes: number; questions: number; max_marks: number; last_score: number | null };

export type TestRun = {
  test_attempt_id: string;
  title: string;
  instructions: string;
  duration_minutes: number;
  started_at: string;
  ends_at: string;
  answers: Record<string, Record<string, unknown>>;
  items: { position: number; section: string; marks: number; negative_marks: number; question: Question }[];
};

export type TestReport = {
  test_attempt_id: string;
  title: string;
  score: number;
  max_score: number;
  percent: number;
  accuracy: number;
  attempted: number;
  questions: number;
  time_taken_seconds: number;
  sections: { section: string; score: number; max: number; correct: number; wrong: number; unattempted: number }[];
  weak_concepts: string[];
  review: {
    question: Question;
    response: Record<string, unknown>;
    marks: number;
    max_marks: number;
    is_correct: boolean;
    answered: boolean;
    correct_answer: unknown;
    explanation: string;
    feedback: Feedback;
  }[];
};
