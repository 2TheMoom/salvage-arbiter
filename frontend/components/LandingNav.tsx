"use client";

import Link from "next/link";
import { Github } from "lucide-react";
import { Logo, LogoMark } from "./Logo";
import { Button } from "./ui/button";

export function LandingNav() {
  return (
    <header className="fixed top-0 left-0 right-0 z-50 border-b border-white/5 bg-black/60 backdrop-blur-xl">
      <div className="max-w-7xl mx-auto px-4 md:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <div className="flex md:hidden">
            <LogoMark size="md" />
          </div>
          <div className="hidden md:flex">
            <Logo size="md" />
          </div>

          <div className="flex items-center gap-4">
            <a
              href="https://github.com/2TheMoom/salvage-arbiter"
              target="_blank"
              rel="noopener noreferrer"
              className="hidden sm:flex items-center gap-1.5 text-sm text-muted-foreground hover:text-accent transition-colors"
            >
              <Github className="w-4 h-4" />
              GitHub
            </a>
            <Button asChild variant="gradient" size="sm">
              <Link href="/app">Launch App</Link>
            </Button>
          </div>
        </div>
      </div>
    </header>
  );
}
