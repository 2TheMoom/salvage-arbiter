"use client";

import { useState, useEffect } from "react";
import { FileCheck2, ShieldCheck } from "lucide-react";
import { AccountPanel } from "./AccountPanel";
import { SubmitClaimModal } from "./SubmitClaimModal";
import { useClaims } from "@/lib/hooks/useRecoveryArbiter";
import { Logo, LogoMark } from "./Logo";

export function Navbar() {
  const [isScrolled, setIsScrolled] = useState(false);
  const [scrollProgress, setScrollProgress] = useState(0);
  const { data: claims } = useClaims();

  useEffect(() => {
    const handleScroll = () => {
      const scrollY = window.scrollY;
      const threshold = 80;

      setIsScrolled(scrollY > 20);

      // Calculate progress from 0 to 1 for smoother animations
      const progress = Math.min(Math.max((scrollY - 10) / threshold, 0), 1);
      setScrollProgress(progress);
    };

    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  // Minimal variant with scroll animations
  const paddingTop = Math.round(scrollProgress * 16); // 0-16px padding
  const headerHeight = 64 - Math.round(scrollProgress * 8); // 64px to 56px

  // Only apply border radius on desktop (md breakpoint and up)
  const getBorderRadius = () => {
    if (typeof window !== 'undefined' && window.innerWidth >= 768) {
      return Math.round(scrollProgress * 9999); // Fully rounded when scrolled on desktop
    }
    return 0; // No rounding on mobile
  };
  const borderRadius = getBorderRadius();

  const totalClaims = claims?.length || 0;
  const adjudicatedClaims = claims?.filter(claim => claim.status !== "pending").length || 0;

  return (
    <header
      className="fixed top-0 left-0 right-0 z-50 transition-all duration-500 ease-out"
      style={{ paddingTop: `${paddingTop}px` }}
    >
      <div
        className="transition-all duration-500 ease-out"
        style={{
          width: '100%',
          maxWidth: isScrolled ? '80rem' : '100%',
          margin: '0 auto',
          borderRadius: `${borderRadius}px`,
        }}
      >
        <div
          className="backdrop-blur-xl border transition-all duration-500 ease-out md:rounded-none"
          style={{
            borderColor: `oklch(0.3 0.02 0 / ${0.4 + scrollProgress * 0.4})`,
            background: `linear-gradient(135deg, oklch(0.18 0.01 0 / ${0.1 + scrollProgress * 0.3}) 0%, oklch(0.15 0.01 0 / ${0.05 + scrollProgress * 0.25}) 50%, oklch(0.16 0.01 0 / ${0.08 + scrollProgress * 0.27}) 100%)`,
            borderRadius: `${borderRadius}px`,
            borderWidth: '1px',
            borderLeftWidth: isScrolled ? '1px' : '0px',
            borderRightWidth: isScrolled ? '1px' : '0px',
            borderTopWidth: isScrolled ? '1px' : '0px',
            boxShadow: isScrolled
              ? '0 32px 64px 0 rgba(0, 0, 0, 0.2), inset 0 1px 0 0 oklch(0.3 0.02 0 / 0.3)'
              : 'none',
            backdropFilter: 'blur(16px) saturate(180%)',
            WebkitBackdropFilter: 'blur(16px) saturate(180%)',
          }}
        >
          <div
            className="px-6 transition-all duration-500 mx-auto"
            style={{
              maxWidth: isScrolled ? '80rem' : '112rem',
            }}
          >
            <div
              className="flex items-center justify-between transition-all duration-500"
              style={{ height: `${headerHeight}px` }}
            >
              {/* Left: Logo */}
              <div className="flex items-center gap-3 min-w-0">
                {/* Show mark only on mobile, full logo on desktop.
                    Wrapped in plain divs rather than passing "hidden"/"flex"
                    into Logo's own className: its internal wrapper hardcodes
                    "inline-flex", which can win the display-property cascade
                    over an externally-passed "hidden" depending on Tailwind's
                    generated class order, making both logos render at once. */}
                <div className="flex md:hidden shrink-0">
                  <LogoMark size="md" />
                </div>
                <div className="hidden md:flex shrink-0">
                  <Logo size="md" />
                </div>
                <span className="text-lg md:text-xl font-bold ml-2 hidden sm:inline truncate">
                  Salvage Arbiter
                </span>
              </div>

              {/* Center: Stats */}
              <div className="hidden md:flex items-center gap-2">
                <div className="stat-pill">
                  <FileCheck2 className="w-3.5 h-3.5 text-accent" />
                  <span className="font-semibold text-foreground">{totalClaims}</span>
                  Claims
                </div>
                <div className="stat-pill">
                  <ShieldCheck className="w-3.5 h-3.5 text-accent" />
                  <span className="font-semibold text-foreground">{adjudicatedClaims}</span>
                  Adjudicated
                </div>
              </div>

              {/* Right: Actions */}
              <div className="flex items-center gap-3">
                <SubmitClaimModal />
                <AccountPanel />
              </div>
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}
