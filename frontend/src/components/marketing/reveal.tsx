"use client";

import { useEffect, useRef, useState, type ElementType, type ReactNode } from "react";

/**
 * Marks its element `data-visible="true"` the first time it scrolls into view.
 * Styling (`.reveal`, `.wipe`, `.ink-mark`) lives in globals.css.
 */
export function Reveal({
  as: Tag = "div",
  className = "reveal",
  delay = 0,
  children,
}: {
  as?: ElementType;
  className?: string;
  delay?: number;
  children: ReactNode;
}) {
  const ref = useRef<HTMLElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: "0px 0px -12% 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <Tag ref={ref} className={className} data-visible={visible} style={{ "--delay": `${delay}ms` } as React.CSSProperties}>
      {children}
    </Tag>
  );
}
