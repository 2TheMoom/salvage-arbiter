"use client";

import { Navbar } from "@/components/Navbar";
import { ClaimsTable } from "@/components/ClaimsTable";
import { MyClaimsPanel } from "@/components/MyClaimsPanel";

export default function HomePage() {
  return (
    <div className="min-h-screen flex flex-col">
      {/* Navbar */}
      <Navbar />

      {/* Main Content - Padding to account for fixed navbar */}
      <main className="flex-grow pt-20 pb-12 px-4 md:px-6 lg:px-8">
        <div className="max-w-7xl mx-auto">
          {/* Hero Section */}
          <div className="text-center mb-8 animate-fade-in">
            <h1 className="text-4xl md:text-5xl lg:text-6xl font-bold mb-4">
              Salvage Arbiter
            </h1>
            <p className="text-lg md:text-xl text-muted-foreground max-w-2xl mx-auto">
              AI-adjudicated fund-recovery claims on GenLayer.
              <br />
              Submit evidence, let validators reach a verdict, and get an on-chain attestation.
            </p>
          </div>

          {/* Main Grid Layout - 2/1 columns on desktop, stacked on mobile */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 lg:gap-8">
            {/* Left Column - Claims Table (67% on desktop) */}
            <div className="lg:col-span-8 animate-slide-up">
              <ClaimsTable />
            </div>

            {/* Right Column - My Claims (33% on desktop) */}
            <div className="lg:col-span-4 animate-slide-up" style={{ animationDelay: "100ms" }}>
              <MyClaimsPanel />
            </div>
          </div>

          {/* Info Section */}
          <div className="mt-8 glass-card p-6 md:p-8 animate-fade-in" style={{ animationDelay: "200ms" }}>
            <h2 className="text-2xl font-bold mb-4">How it Works</h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div className="space-y-2">
                <div className="text-accent font-bold text-lg">1. Submit a Claim</div>
                <p className="text-sm text-muted-foreground">
                  Connect your wallet, name the drained wallet you're claiming, and point to public evidence of ownership.
                </p>
              </div>
              <div className="space-y-2">
                <div className="text-accent font-bold text-lg">2. AI Adjudication</div>
                <p className="text-sm text-muted-foreground">
                  Validators independently fetch your evidence and reason over it with an LLM, reaching consensus via GenLayer's equivalence principle.
                </p>
              </div>
              <div className="space-y-2">
                <div className="text-accent font-bold text-lg">3. On-Chain Verdict</div>
                <p className="text-sm text-muted-foreground">
                  The claim is marked approved, denied, or insufficient, with a confidence score and reasoning anyone can verify.
                </p>
              </div>
            </div>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-white/10 py-2">
        <div className="max-w-7xl mx-auto px-4 md:px-6 lg:px-8">
          <div className="flex items-center justify-center gap-6 text-sm text-muted-foreground">
              <a
                href="https://genlayer.com"
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-accent transition-colors"
              >
                Powered by GenLayer
              </a>
              <a
                href="https://studio.genlayer.com"
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-accent transition-colors"
              >
                Studio
              </a>
              <a
                href="https://docs.genlayer.com"
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-accent transition-colors"
              >
                Docs
              </a>
              <a
                href="https://github.com/2TheMoom/salvage-arbiter"
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-accent transition-colors"
              >
                GitHub
              </a>
          </div>
        </div>
      </footer>
    </div>
  );
}
