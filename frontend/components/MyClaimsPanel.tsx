"use client";

import { ShieldCheck, ShieldX, ShieldQuestion, Clock, Loader2, AlertCircle, User } from "lucide-react";
import { useClaimsByAddress, useRecoveryArbiterContract } from "@/lib/hooks/useRecoveryArbiter";
import { useWallet } from "@/lib/genlayer/wallet";
import { Button } from "./ui/button";
import type { Claim } from "@/lib/contracts/types";
import { MAX_APPEALS } from "@/lib/contracts/types";

const STATUS_ICON: Record<Claim["status"], React.ReactNode> = {
  approved: <ShieldCheck className="w-4 h-4 text-green-400" />,
  denied: <ShieldX className="w-4 h-4 text-red-400" />,
  insufficient: <ShieldQuestion className="w-4 h-4 text-orange-400" />,
  pending: <Clock className="w-4 h-4 text-yellow-400" />,
};

export function MyClaimsPanel() {
  const contract = useRecoveryArbiterContract();
  const { address, isConnected, isLoading: isWalletLoading, connectWallet } = useWallet();
  const { data: claims, isLoading, isError } = useClaimsByAddress(address);

  if (!isConnected) {
    return (
      <div className="brand-card p-6">
        <h2 className="text-xl font-bold mb-4 flex items-center gap-2">
          <User className="w-5 h-5 text-accent" />
          My Claims
        </h2>
        <div className="text-center py-8 space-y-4">
          <User className="w-12 h-12 mx-auto text-muted-foreground opacity-30" />
          <p className="text-sm text-muted-foreground">Connect your wallet to see your claims</p>
          <Button
            variant="gradient"
            size="sm"
            onClick={() => {
              connectWallet().catch(() => {});
            }}
            disabled={isWalletLoading}
          >
            Connect Wallet
          </Button>
        </div>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="brand-card p-6">
        <h2 className="text-xl font-bold mb-4 flex items-center gap-2">
          <User className="w-5 h-5 text-accent" />
          My Claims
        </h2>
        <div className="flex items-center justify-center py-8">
          <Loader2 className="w-6 h-6 animate-spin text-accent" />
        </div>
      </div>
    );
  }

  if (!contract) {
    return (
      <div className="brand-card p-6">
        <h2 className="text-xl font-bold mb-4 flex items-center gap-2">
          <User className="w-5 h-5 text-accent" />
          My Claims
        </h2>
        <div className="text-center py-8 space-y-3">
          <AlertCircle className="w-12 h-12 mx-auto text-yellow-400 opacity-60" />
          <div className="space-y-1">
            <p className="text-sm text-muted-foreground">Setup Required</p>
            <p className="text-xs text-muted-foreground">Contract address not configured</p>
          </div>
        </div>
      </div>
    );
  }

  if (isError || !claims) {
    return (
      <div className="brand-card p-6">
        <h2 className="text-xl font-bold mb-4 flex items-center gap-2">
          <User className="w-5 h-5 text-accent" />
          My Claims
        </h2>
        <div className="text-center py-8">
          <p className="text-sm text-destructive">Failed to load your claims</p>
        </div>
      </div>
    );
  }

  if (claims.length === 0) {
    return (
      <div className="brand-card p-6">
        <h2 className="text-xl font-bold mb-4 flex items-center gap-2">
          <User className="w-5 h-5 text-accent" />
          My Claims
        </h2>
        <div className="text-center py-8">
          <ShieldQuestion className="w-12 h-12 mx-auto text-muted-foreground opacity-30 mb-3" />
          <p className="text-sm text-muted-foreground">You haven't submitted any claims yet</p>
        </div>
      </div>
    );
  }

  return (
    <div className="brand-card p-6">
      <h2 className="text-xl font-bold mb-4 flex items-center gap-2">
        <User className="w-5 h-5 text-accent" />
        My Claims
      </h2>

      <div className="space-y-2">
        {claims.map((claim) => (
          <div key={claim.id} className="flex items-center gap-3 p-3 rounded-lg hover:bg-white/5 transition-all">
            <div className="flex-shrink-0">{STATUS_ICON[claim.status]}</div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-mono truncate" title={claim.drained_wallet}>
                {claim.drained_wallet}
              </p>
              <p className="text-xs text-muted-foreground capitalize">
                {claim.status}
                {claim.appeal_count > 0 && ` · appealed ${claim.appeal_count}/${MAX_APPEALS}`}
              </p>
            </div>
            {claim.status !== "pending" && (
              <div className="flex-shrink-0 text-right">
                <span className="text-sm font-bold text-accent">{claim.verdict_confidence}%</span>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
