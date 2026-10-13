"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

import { isStaff, useAuth } from "@/components/auth";
import { cx } from "@/components/ui";

const LEARNER_LINKS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/courses", label: "Courses" },
  { href: "/reviews", label: "Revision" },
  { href: "/lab/code", label: "Code lab" },
  { href: "/lab/language", label: "Language lab" },
  { href: "/career", label: "Career" },
];

export function Nav() {
  const { me, logout } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const links = me ? [...LEARNER_LINKS, ...(isStaff(me.role) ? [{ href: "/admin", label: "Admin" }] : [])] : [{ href: "/courses", label: "Courses" }];

  return (
    <nav className="sticky top-0 z-30 border-b border-line bg-surface/90 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3">
        <Link href={me ? "/dashboard" : "/"} className="flex items-center gap-2 font-bold tracking-tight">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-brand-600 text-sm text-white">EV</span>
          <span>EduVerse AI</span>
        </Link>
        <button className="ml-auto rounded-md p-2 md:hidden" aria-label="Menu" aria-expanded={open} onClick={() => setOpen(!open)}>
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 5h14M3 10h14M3 15h14" />
          </svg>
        </button>
        <div className={cx("absolute inset-x-0 top-full border-b border-line bg-surface md:static md:flex md:flex-1 md:items-center md:border-0 md:bg-transparent", open ? "block" : "hidden")}>
          <ul className="flex flex-col gap-1 px-4 py-2 md:flex-row md:px-0 md:py-0">
            {links.map((l) => (
              <li key={l.href}>
                <Link
                  href={l.href}
                  onClick={() => setOpen(false)}
                  className={cx(
                    "block rounded-md px-3 py-1.5 text-sm font-medium",
                    pathname.startsWith(l.href) ? "bg-brand-50 text-brand-700 dark:bg-brand-900/40 dark:text-brand-200" : "text-muted hover:text-ink",
                  )}
                >
                  {l.label}
                </Link>
              </li>
            ))}
          </ul>
          <div className="flex items-center gap-2 px-4 pb-3 md:ml-auto md:p-0">
            {me ? (
              <>
                <Link href="/profile" className="text-sm text-muted hover:text-ink" onClick={() => setOpen(false)}>
                  {me.name}
                </Link>
                <button
                  className="rounded-md px-3 py-1.5 text-sm text-muted hover:bg-surface-2 hover:text-ink"
                  onClick={async () => {
                    // Leave the protected page first, so its guard does not bounce us to /login?next=…
                    router.replace("/login");
                    await logout();
                  }}
                >
                  Sign out
                </button>
              </>
            ) : (
              <>
                <Link href="/login" className="rounded-md px-3 py-1.5 text-sm font-medium text-muted hover:text-ink">
                  Sign in
                </Link>
                <Link href="/register" className="rounded-lg bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700">
                  Start learning
                </Link>
              </>
            )}
          </div>
        </div>
      </div>
    </nav>
  );
}
