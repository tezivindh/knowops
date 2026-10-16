"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Logo } from "@/components/marketing/logo";

/** Sticky header: hides while scrolling down, returns on any scroll up. */
export function LandingHeader() {
  const [hidden, setHidden] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const lastY = useRef(0);

  useEffect(() => {
    let frame = 0;
    const onScroll = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const y = window.scrollY;
        const delta = y - lastY.current;
        if (Math.abs(delta) > 6) {
          setHidden(delta > 0 && y > 120);
          lastY.current = y;
        }
        setScrolled(y > 8);
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", onScroll);
    };
  }, []);

  return (
    <header
      className={`sticky top-0 z-40 border-b bg-bg/90 backdrop-blur-[6px] transition-[transform,border-color] duration-300 ease-[var(--ease-out)] ${
        hidden ? "-translate-y-full" : "translate-y-0"
      } ${scrolled ? "border-rule" : "border-transparent"}`}
    >
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
        <Logo />
        <nav className="flex items-center gap-1 text-[13.5px]">
          <a href="#how" className="hidden rounded-md px-3 py-1.5 text-ink-2 hover:text-ink sm:block">
            How it works
          </a>
          <a href="#features" className="hidden rounded-md px-3 py-1.5 text-ink-2 hover:text-ink sm:block">
            Features
          </a>
          <Link href="/login" className="rounded-md px-3 py-1.5 text-ink-2 hover:text-ink">
            Sign in
          </Link>
          <Link href="/register" className="press rounded-md bg-ink px-3.5 py-1.5 font-medium text-bg hover:opacity-90">
            Get started
          </Link>
        </nav>
      </div>
    </header>
  );
}
