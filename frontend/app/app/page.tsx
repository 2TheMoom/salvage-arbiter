"use client";

import { Navbar } from "@/components/Navbar";
import { ClaimsTable } from "@/components/ClaimsTable";
import { MyClaimsPanel } from "@/components/MyClaimsPanel";
import { DeploymentBanner } from "@/components/DeploymentBanner";

export default function AppPage() {
  return (
    <div className="min-h-screen flex flex-col">
      <Navbar />

      <main className="flex-grow pt-24 pb-16 px-4 md:px-6 lg:px-8">
        <div className="max-w-7xl mx-auto space-y-6">
          <DeploymentBanner />

          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 lg:gap-8">
            <div className="lg:col-span-8 animate-slide-up">
              <ClaimsTable />
            </div>

            <div className="lg:col-span-4 animate-slide-up" style={{ animationDelay: "100ms" }}>
              <MyClaimsPanel />
            </div>
          </div>
        </div>
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
