"use client";

import Link from "next/link";
import { Wallet, Sparkles, ShieldCheck, ArrowRight, Github } from "lucide-react";
import { LandingNav } from "@/components/LandingNav";
import { DeploymentBanner } from "@/components/DeploymentBanner";
import { Logo } from "@/components/Logo";
import { Button } from "@/components/ui/button";

const STEPS = [
  {
    icon: Wallet,
    title: "Submit a Claim",
    description:
      "Connect your wallet, name the drained wallet you're claiming, and point to public evidence of ownership.",
  },
  {
    icon: Sparkles,
    title: "AI Adjudication",
    description:
      "Validators independently fetch your evidence and reason over it with an LLM, reaching consensus via GenLayer's equivalence principle.",
  },
  {
    icon: ShieldCheck,
    title: "On-Chain Verdict",
    description:
      "The claim is marked approved, denied, or insufficient, with a confidence score and reasoning anyone can verify.",
  },
];

export default function LandingPage() {
  return (
    <div className="min-h-screen flex flex-col">
      <LandingNav />

      <main className="flex-grow pt-16">
        {/* Hero */}
        <section className="px-4 md:px-6 lg:px-8 pt-20 pb-16 text-center">
          <div className="max-w-4xl mx-auto animate-fade-in">
            <div className="stat-pill mx-auto mb-8">
              <span className="status-dot" />
              Live on GenLayer Bradbury Testnet
            </div>

            <div className="flex justify-center mb-6">
              <Logo variant="mark" size="lg" className="scale-[2.5]" />
            </div>

            <h1 className="font-[family-name:var(--font-display)] text-5xl md:text-6xl lg:text-7xl font-semibold mb-6 leading-[1.05]">
              Salvage <span className="text-gradient italic">Arbiter</span>
            </h1>
            <p className="text-lg md:text-xl text-muted-foreground max-w-2xl mx-auto mb-10">
              AI-adjudicated fund-recovery claims on GenLayer. Submit evidence, let
              independent validators reach a verdict, and get an on-chain attestation
              instead of relying on manual, offline trust.
            </p>

            <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
              <Button asChild variant="gradient" size="lg" className="w-full sm:w-auto">
                <Link href="/app">
                  Launch App
                  <ArrowRight className="w-4 h-4" />
                </Link>
              </Button>
              <Button asChild variant="outline" size="lg" className="w-full sm:w-auto">
                <a
                  href="https://github.com/2TheMoom/salvage-arbiter"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <Github className="w-4 h-4" />
                  View Source
                </a>
              </Button>
            </div>
          </div>
        </section>

        {/* Deployment proof strip */}
        <section className="px-4 md:px-6 lg:px-8 mb-20">
          <div className="max-w-4xl mx-auto animate-fade-in" style={{ animationDelay: "80ms" }}>
            <DeploymentBanner />
          </div>
        </section>

        {/* How it Works */}
        <section className="px-4 md:px-6 lg:px-8 pb-24">
          <div className="max-w-6xl mx-auto">
            <div className="text-center mb-10">
              <h2 className="font-[family-name:var(--font-display)] text-3xl md:text-4xl font-semibold mb-3">
                How it Works
              </h2>
              <p className="text-muted-foreground max-w-xl mx-auto">
                No single party decides your claim - independent validators do, and their
                reasoning is recorded on-chain for anyone to check.
              </p>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              {STEPS.map((step, index) => (
                <div
                  key={step.title}
                  className="brand-card brand-card-hover p-6 space-y-4 animate-slide-up"
                  style={{ animationDelay: `${index * 100}ms` }}
                >
                  <div className="flex items-center gap-3">
                    <span className="icon-badge">
                      <step.icon className="w-5 h-5" />
                    </span>
                    <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                      Step {index + 1}
                    </span>
                  </div>
                  <div className="font-bold text-lg">{step.title}</div>
                  <p className="text-sm text-muted-foreground">{step.description}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Closing CTA */}
        <section className="px-4 md:px-6 lg:px-8 pb-24">
          <div className="max-w-4xl mx-auto brand-card p-10 md:p-14 text-center space-y-6">
            <h2 className="font-[family-name:var(--font-display)] text-2xl md:text-3xl font-semibold">
              Ready to submit a claim?
            </h2>
            <p className="text-muted-foreground max-w-lg mx-auto">
              Connect your wallet and get an AI-adjudicated, on-chain verdict on your
              fund-recovery claim.
            </p>
            <Button asChild variant="gradient" size="lg">
              <Link href="/app">
                Launch App
                <ArrowRight className="w-4 h-4" />
              </Link>
            </Button>
          </div>
        </section>
      </main>

      <footer className="border-t border-white/10 py-4">
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
