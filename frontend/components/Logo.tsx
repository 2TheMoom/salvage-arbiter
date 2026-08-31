/**
 * Salvage Arbiter Logo
 *
 * Mark concept: "Consensus Point" - three independent arcs (evidence /
 * validators) converge on a single faceted point (the on-chain verdict),
 * echoing the same converging-arcs motif Salvage's own icon uses, but
 * resolving into a cut-gem facet in Arbiter's gold/coral palette instead
 * of a plain dot - "the verdict, cut from what was salvaged."
 *
 * Variants:
 * - "full": mark + wordmark
 * - "mark": mark only
 * - "wordmark": wordmark only
 */

import React from 'react';

export type LogoVariant = 'full' | 'mark' | 'wordmark';
export type LogoSize = 'sm' | 'md' | 'lg';

interface LogoProps {
  variant?: LogoVariant;
  size?: LogoSize;
  className?: string;
}

const sizeMap = {
  sm: { mark: 'w-5 h-5', text: 'text-base' },
  md: { mark: 'w-6 h-6', text: 'text-xl' },
  lg: { mark: 'w-8 h-8', text: 'text-2xl' },
};

export function Logo({ variant = 'full', size = 'md', className = '' }: LogoProps) {
  const { mark: markSize, text: textSize } = sizeMap[size];
  // useId (not a module-level counter) so the id matches between the
  // server-rendered HTML and the client hydration pass - a counter that
  // increments during render produces different values on each side and
  // triggers a hydration mismatch.
  const gradientId = `arbiter-mark-${React.useId()}`;

  const Mark = () => (
    <svg
      className={markSize}
      viewBox="0 0 52 52"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-label="Salvage Arbiter"
    >
      <defs>
        <linearGradient id={gradientId} x1="8" y1="44" x2="49" y2="38" gradientUnits="userSpaceOnUse">
          <stop stopColor="#F5C15B" />
          <stop offset="1" stopColor="#FF7A57" />
        </linearGradient>
      </defs>
      <path
        d="M 8 44 A 26 26 0 0 1 44 8"
        stroke={`url(#${gradientId})`}
        strokeWidth="2.5"
        strokeLinecap="round"
        opacity="0.22"
      />
      <path
        d="M 13 44 A 21 21 0 0 1 44 13"
        stroke={`url(#${gradientId})`}
        strokeWidth="2.5"
        strokeLinecap="round"
        opacity="0.5"
      />
      <path
        d="M 19 44 A 15 15 0 0 1 44 19"
        stroke={`url(#${gradientId})`}
        strokeWidth="2.8"
        strokeLinecap="round"
        opacity="0.9"
      />
      <path d="M44 38 L49 44 L44 50 L39 44 Z" fill={`url(#${gradientId})`} />
      <circle cx="44" cy="44" r="9" stroke={`url(#${gradientId})`} strokeWidth="1.2" opacity="0.3" />
    </svg>
  );

  const Wordmark = () => (
    <span
      className={`${textSize} font-bold text-foreground font-[family-name:var(--font-display)]`}
      style={{ letterSpacing: '-0.02em' }}
    >
      Salvage <span className="text-gradient">Arbiter</span>
    </span>
  );

  if (variant === 'mark') {
    return (
      <div className={`inline-flex items-center ${className}`}>
        <Mark />
      </div>
    );
  }

  if (variant === 'wordmark') {
    return (
      <div className={`inline-flex items-center ${className}`}>
        <Wordmark />
      </div>
    );
  }

  return (
    <div className={`inline-flex items-center gap-2 ${className}`}>
      <Mark />
      <Wordmark />
    </div>
  );
}

export function LogoFull(props: Omit<LogoProps, 'variant'>) {
  return <Logo {...props} variant="full" />;
}

export function LogoMark(props: Omit<LogoProps, 'variant'>) {
  return <Logo {...props} variant="mark" />;
}

export function LogoWordmark(props: Omit<LogoProps, 'variant'>) {
  return <Logo {...props} variant="wordmark" />;
}
