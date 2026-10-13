"use client";

import { useState } from "react";

import { RequireAuth } from "@/components/auth";
import { PracticeSession } from "@/components/practice";
import { ErrorNote, Loading, PageHeader, Select } from "@/components/ui";
import { useApi } from "@/lib/hooks";
import type { CourseDetail, TreeNode } from "@/lib/types";

const COURSE = "python-fundamentals";

function concepts(nodes: TreeNode[]): { id: string; title: string }[] {
  return nodes.flatMap((n) => [...n.concepts.map((c) => ({ id: c.id, title: c.title })), ...concepts(n.children)]);
}

function CodeLab() {
  const course = useApi<CourseDetail>(`/courses/${COURSE}`);
  const [concept, setConcept] = useState("");
  if (course.loading) return <Loading />;
  if (course.error || !course.data) return <ErrorNote error={course.error} />;
  return (
    <div className="space-y-6">
      <PageHeader
        title="Code lab"
        subtitle="Write Python, run the examples, then submit to run hidden tests and get a code review (quality, performance, security)."
        action={
          <Select aria-label="Topic" value={concept} onChange={(e) => setConcept(e.target.value)} className="w-64">
            <option value="">Adaptive: pick for me</option>
            {concepts(course.data.tree).map((c) => (
              <option key={c.id} value={c.id}>
                {c.title}
              </option>
            ))}
          </Select>
        }
      />
      <PracticeSession key={concept || "adaptive"} course={concept ? undefined : COURSE} concept={concept || undefined} types="coding" />
    </div>
  );
}

export default function CodeLabPage() {
  return (
    <RequireAuth>
      <CodeLab />
    </RequireAuth>
  );
}
