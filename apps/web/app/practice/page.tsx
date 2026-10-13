"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { RequireAuth } from "@/components/auth";
import { PracticeSession } from "@/components/practice";
import { ButtonLink, Empty, PageHeader } from "@/components/ui";

function Practice() {
  const params = useSearchParams();
  const course = params.get("course") ?? undefined;
  const concept = params.get("concept") ?? undefined;
  const types = params.get("types") ?? undefined;
  if (!course && !concept) {
    return (
      <Empty title="Pick a course or a concept to practise">
        <ButtonLink href="/dashboard" className="mt-3">
          Go to my dashboard
        </ButtonLink>
      </Empty>
    );
  }
  return (
    <>
      <PageHeader title="Practice" subtitle="Questions adapt to your mastery. Use hints when stuck; they cost a little mastery gain, never a wrong mark." />
      <PracticeSession key={`${course}-${concept}-${types}`} course={course} concept={concept} types={types} />
    </>
  );
}

export default function PracticePage() {
  return (
    <RequireAuth>
      <Suspense>
        <Practice />
      </Suspense>
    </RequireAuth>
  );
}
