"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "@/components/auth";
import { ButtonLink, Card } from "@/components/ui";

const ROLES = [
  { title: "AI Teacher", body: "Every concept at four levels, from plain-language basics to expert depth, in English and Telugu, with diagrams." },
  { title: "Mentor", body: "A daily plan built from your mastery: spaced revision on days 3, 7, 15 and 30, weak areas first." },
  { title: "Examiner", body: "Exam-pattern mock tests with negative marking, and rubric-based scoring of written and interview answers." },
  { title: "Coding assistant", body: "Write Python in the browser, run hidden tests, and get a code review on quality, performance and security." },
  { title: "Language partner", body: "Conversation practice with gentle corrections and pronunciation drills scored from your voice." },
  { title: "Career guide", body: "Realistic paths for your goal, with the courses that get you there." },
];

export default function Home() {
  const { me, ready } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (ready && me) router.replace("/dashboard");
  }, [ready, me, router]);

  return (
    <div className="space-y-12">
      <section className="rounded-2xl bg-gradient-to-br from-brand-600 to-brand-900 px-6 py-14 text-white sm:px-12">
        <p className="text-sm font-medium uppercase tracking-widest text-brand-200">AI Learning Operating System</p>
        <h1 className="mt-3 max-w-2xl text-4xl font-bold leading-tight sm:text-5xl">Learn for understanding. Practise for the exam.</h1>
        <p className="mt-4 max-w-xl text-lg text-brand-100">
          SSC, CBSE, CA Foundation, Python, spoken English and interviews, taught concept-first and adapted to what you already know.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <ButtonLink href="/register" className="bg-white !text-brand-700 hover:bg-brand-50">
            Create a free account
          </ButtonLink>
          <ButtonLink href="/courses" variant="ghost" className="!text-white ring-1 ring-white/40 hover:bg-white/10">
            Browse courses
          </ButtonLink>
        </div>
      </section>
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {ROLES.map((r) => (
          <Card key={r.title} title={r.title}>
            <p className="text-sm text-muted">{r.body}</p>
          </Card>
        ))}
      </section>
    </div>
  );
}
