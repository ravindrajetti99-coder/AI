"use client";

import { useEffect, useId, useRef, useState } from "react";

/** Renders Mermaid source client-side. `securityLevel: strict` sanitises AI-written diagrams. */
export function Mermaid({ code }: { code: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const id = useId().replace(/:/g, "");
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
        mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: dark ? "dark" : "default" });
        const { svg } = await mermaid.render(`mmd-${id}`, code);
        if (live && ref.current) ref.current.innerHTML = svg;
      } catch {
        if (live) setFailed(true);
      }
    })();
    return () => {
      live = false;
    };
  }, [code, id]);

  if (failed) return <pre className="overflow-x-auto rounded-lg bg-surface-2 p-3 text-xs">{code}</pre>;
  return <div ref={ref} className="flex justify-center overflow-x-auto py-2 [&_svg]:max-w-full" aria-label="Diagram" role="img" />;
}
