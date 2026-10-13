"use client";

import Link from "next/link";
import { useState } from "react";

import { accent, Badge, cx, Empty, ErrorNote, Loading, PageHeader } from "@/components/ui";
import { useApi } from "@/lib/hooks";
import type { Course, Domain } from "@/lib/types";

export default function CoursesPage() {
  const [domain, setDomain] = useState("");
  const [q, setQ] = useState("");
  const domains = useApi<Domain[]>("/domains");
  const courses = useApi<Course[]>("/courses", { domain, q });

  return (
    <div>
      <PageHeader title="Courses" subtitle="Exams, school subjects, professional courses, programming, languages and career skills." />
      <div className="mb-6 flex flex-wrap items-center gap-2">
        <button onClick={() => setDomain("")} className={cx("rounded-full px-3 py-1 text-sm", domain === "" ? "bg-brand-600 text-white" : "bg-surface-2 text-muted hover:text-ink")}>
          All
        </button>
        {domains.data?.map((d) => (
          <button
            key={d.code}
            onClick={() => setDomain(d.code)}
            className={cx("rounded-full px-3 py-1 text-sm", domain === d.code ? "bg-brand-600 text-white" : "bg-surface-2 text-muted hover:text-ink")}
          >
            {d.name} <span className="opacity-70">{d.course_count}</span>
          </button>
        ))}
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search courses"
          aria-label="Search courses"
          className="ml-auto w-full rounded-lg border border-line bg-surface px-3 py-1.5 text-sm sm:w-64"
        />
      </div>
      <ErrorNote error={courses.error} />
      {courses.loading ? (
        <Loading />
      ) : courses.data?.length === 0 ? (
        <Empty title="No courses match" />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {courses.data?.map((c) => (
            <Link key={c.id} href={`/courses/${c.slug}`} className="group flex flex-col overflow-hidden rounded-xl border border-line bg-surface shadow-sm transition-shadow hover:shadow-md">
              <div className={cx("h-2", accent(c.color))} />
              <div className="flex flex-1 flex-col p-5">
                <h2 className="font-semibold group-hover:text-brand-600">{c.title}</h2>
                <p className="mt-2 line-clamp-3 flex-1 text-sm text-muted">{c.description}</p>
                <div className="mt-4 flex flex-wrap gap-2">
                  <Badge>{c.level}</Badge>
                  <Badge>{c.concept_count} concepts</Badge>
                  <Badge>{c.question_count} questions</Badge>
                  {c.locales.includes("te") && <Badge tone="brand">English + తెలుగు</Badge>}
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
