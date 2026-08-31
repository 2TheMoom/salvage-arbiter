"use client";

import { Loader2, ShieldCheck, ShieldX, ShieldQuestion, Clock, AlertCircle } from "lucide-react";
import { useClaims, useAdjudicate, useRecoveryArbiterContract } from "@/lib/hooks/useRecoveryArbiter";
import { useWallet } from "@/lib/genlayer/wallet";
import { error } from "@/lib/utils/toast";
import { AddressDisplay } from "./AddressDisplay";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";
import type { Claim } from "@/lib/contracts/types";

export function ClaimsTable() {
  const contract = useRecoveryArbiterContract();
  const { data: claims, isLoading, isError } = useClaims();
  const { address, isConnected, isLoading: isWalletLoading } = useWallet();
  const { adjudicate, isAdjudicating, adjudicatingClaimId } = useAdjudicate();

  const handleAdjudicate = (claimId: string) => {
    if (!address) {
      error("Please connect your wallet to adjudicate a claim");
      return;
    }
    adjudicate(claimId);
  };

  if (isLoading) {
    return (
      <div className="brand-card p-8 flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-8 h-8 animate-spin text-accent" />
          <p className="text-sm text-muted-foreground">Loading claims...</p>
        </div>
      </div>
    );
  }

  if (!contract) {
    return (
      <div className="brand-card p-12">
        <div className="text-center space-y-4">
          <AlertCircle className="w-16 h-16 mx-auto text-yellow-400 opacity-60" />
          <h3 className="text-xl font-bold">Setup Required</h3>
          <div className="space-y-2">
            <p className="text-muted-foreground">Contract address not configured.</p>
            <p className="text-sm text-muted-foreground">
              Please set <code className="bg-muted px-1 py-0.5 rounded text-xs">NEXT_PUBLIC_CONTRACT_ADDRESS</code> in your .env file.
            </p>
          </div>
        </div>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="brand-card p-8">
        <div className="text-center">
          <p className="text-destructive">Failed to load claims. Please try again.</p>
        </div>
      </div>
    );
  }

  if (!claims || claims.length === 0) {
    return (
      <div className="brand-card p-12">
        <div className="text-center space-y-3">
          <ShieldQuestion className="w-16 h-16 mx-auto text-muted-foreground opacity-30" />
          <h3 className="text-xl font-bold">No Claims Yet</h3>
          <p className="text-muted-foreground">
            Be the first to submit a fund-recovery claim!
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {claims.map((claim) => (
        <ClaimRow
          key={claim.id}
          claim={claim}
          currentAddress={address}
          isConnected={isConnected}
          isWalletLoading={isWalletLoading}
          onAdjudicate={handleAdjudicate}
          isAdjudicating={isAdjudicating && adjudicatingClaimId === claim.id}
        />
      ))}
    </div>
  );
}

interface ClaimRowProps {
  claim: Claim;
  currentAddress: string | null;
  isConnected: boolean;
  isWalletLoading: boolean;
  onAdjudicate: (claimId: string) => void;
  isAdjudicating: boolean;
}

function StatusBadge({ status }: { status: Claim["status"] }) {
  switch (status) {
    case "approved":
      return (
        <Badge className="bg-green-500/15 text-green-400 border-green-500/30">
          <ShieldCheck className="w-3 h-3 mr-1" />
          Approved
        </Badge>
      );
    case "denied":
      return (
        <Badge className="bg-red-500/15 text-red-400 border-red-500/30">
          <ShieldX className="w-3 h-3 mr-1" />
          Denied
        </Badge>
      );
    case "insufficient":
      return (
        <Badge className="bg-orange-500/15 text-orange-400 border-orange-500/30">
          <ShieldQuestion className="w-3 h-3 mr-1" />
          Insufficient
        </Badge>
      );
    default:
      return (
        <Badge variant="outline" className="text-yellow-400 border-yellow-500/30">
          <Clock className="w-3 h-3 mr-1" />
          Pending
        </Badge>
      );
  }
}

const STATUS_BAR_COLOR: Record<Claim["status"], string> = {
  approved: "bg-green-400",
  denied: "bg-red-400",
  insufficient: "bg-orange-400",
  pending: "bg-yellow-400",
};

function ConfidenceBar({ value, status }: { value: number; status: Claim["status"] }) {
  return (
    <div className="flex items-center gap-2 w-full max-w-[140px]">
      <div className="h-1.5 flex-1 rounded-full bg-white/10 overflow-hidden">
        <div className={`h-full rounded-full ${STATUS_BAR_COLOR[status]}`} style={{ width: `${value}%` }} />
      </div>
      <span className="text-xs font-semibold text-foreground shrink-0">{value}%</span>
    </div>
  );
}

function ClaimRow({ claim, currentAddress, isConnected, isWalletLoading, onAdjudicate, isAdjudicating }: ClaimRowProps) {
  const isClaimant = currentAddress?.toLowerCase() === claim.claimant?.toLowerCase();
  const canAdjudicate = isConnected && currentAddress && claim.status === "pending" && !isWalletLoading;

  return (
    <div className="brand-card brand-card-hover p-4 sm:p-5 animate-fade-in">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1.5">
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className="text-sm font-mono font-semibold text-foreground break-all"
              title={claim.drained_wallet}
            >
              {claim.drained_wallet.length > 32
                ? `${claim.drained_wallet.slice(0, 16)}...${claim.drained_wallet.slice(-8)}`
                : claim.drained_wallet}
            </span>
            <StatusBadge status={claim.status} />
          </div>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span>Claimant:</span>
            <AddressDisplay address={claim.claimant} maxLength={10} showCopy={true} />
            {isClaimant && (
              <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                You
              </Badge>
            )}
          </div>
        </div>

        {canAdjudicate && (
          <Button
            onClick={() => onAdjudicate(claim.id)}
            disabled={isAdjudicating}
            size="sm"
            variant="gradient"
            className="shrink-0"
          >
            {isAdjudicating ? (
              <>
                <Loader2 className="w-3 h-3 mr-1 animate-spin" />
                Adjudicating...
              </>
            ) : (
              "Adjudicate"
            )}
          </Button>
        )}
      </div>

      {claim.status !== "pending" && (
        <div className="mt-3 pt-3 border-t border-white/5 flex flex-col sm:flex-row sm:items-start gap-3">
          <ConfidenceBar value={claim.verdict_confidence} status={claim.status} />
          <p className="text-xs text-muted-foreground flex-1" title={claim.verdict_reasoning}>
            {claim.verdict_reasoning}
          </p>
        </div>
      )}

      {claim.status === "pending" && !canAdjudicate && (
        <div className="mt-3 pt-3 border-t border-white/5">
          <span className="text-xs text-muted-foreground">Awaiting adjudication</span>
        </div>
      )}
    </div>
  );
}
