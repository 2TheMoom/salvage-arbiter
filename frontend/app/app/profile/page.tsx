"use client";

import { User } from "lucide-react";
import { Navbar } from "@/components/Navbar";
import { WalletDetailsCard } from "@/components/WalletDetailsCard";
import { MyClaimsPanel } from "@/components/MyClaimsPanel";
import { Button } from "@/components/ui/button";
import { useWallet } from "@/lib/genlayer/wallet";

export default function ProfilePage() {
  const { isConnected, isLoading, connectWallet } = useWallet();

  return (
    <div className="min-h-screen flex flex-col">
      <Navbar />

      <main className="flex-grow pt-24 pb-16 px-4 md:px-6 lg:px-8">
        <div className="max-w-3xl mx-auto space-y-6">
          <h1 className="font-[family-name:var(--font-display)] text-3xl font-semibold">
            Profile
          </h1>

          {!isConnected ? (
            <div className="brand-card p-12 text-center space-y-4">
              <User className="w-12 h-12 mx-auto text-muted-foreground opacity-30" />
              <p className="text-muted-foreground">Connect your wallet to view your profile and claim history</p>
              <Button
                variant="gradient"
                onClick={() => connectWallet().catch(() => {})}
                disabled={isLoading}
              >
                Connect Wallet
              </Button>
            </div>
          ) : (
            <>
              <WalletDetailsCard />
              <MyClaimsPanel />
            </>
          )}
        </div>
      </main>
    </div>
  );
}
