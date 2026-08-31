"use client";

import { useState } from "react";
import { User, LogOut, AlertCircle } from "lucide-react";
import { useWallet } from "@/lib/genlayer/wallet";
import { useClaimsByAddress } from "@/lib/hooks/useRecoveryArbiter";
import { error, userRejected } from "@/lib/utils/toast";
import { Button } from "./ui/button";
import { Alert, AlertDescription, AlertTitle } from "./ui/alert";

export function WalletDetailsCard() {
  const { address, isOnCorrectNetwork, isLoading, disconnectWallet, switchWalletAccount } = useWallet();
  const { data: myClaims = [] } = useClaimsByAddress(address);
  const claimCount = myClaims.length;

  const [connectionError, setConnectionError] = useState("");
  const [isSwitching, setIsSwitching] = useState(false);

  const handleSwitchAccount = async () => {
    try {
      setIsSwitching(true);
      setConnectionError("");
      await switchWalletAccount();
    } catch (err: any) {
      if (!err.message?.includes("rejected")) {
        setConnectionError(err.message || "Failed to switch account");
        error("Failed to switch account", {
          description: err.message || "Please try again.",
        });
      } else {
        userRejected("Account switch cancelled");
      }
    } finally {
      setIsSwitching(false);
    }
  };

  return (
    <div className="brand-card p-6 space-y-4">
      <h2 className="text-xl font-bold flex items-center gap-2">
        <User className="w-5 h-5 text-accent" />
        Wallet
      </h2>

      <div className="brand-card p-4 space-y-2">
        <p className="text-sm text-muted-foreground">Your Address</p>
        <code className="text-sm font-mono break-all">{address}</code>
      </div>

      <div className="brand-card p-4 space-y-2">
        <p className="text-sm text-muted-foreground">Your Claims</p>
        <p className="text-2xl font-bold text-accent">{claimCount}</p>
      </div>

      <div className="brand-card p-4 space-y-2">
        <p className="text-sm text-muted-foreground">Network Status</p>
        <div className="flex items-center gap-2">
          <div
            className={`w-2 h-2 rounded-full ${
              isOnCorrectNetwork ? "bg-green-500" : "bg-yellow-500 animate-pulse"
            }`}
          />
          <span className="text-sm">
            {isOnCorrectNetwork ? "Connected to GenLayer" : "Wrong Network"}
          </span>
        </div>
      </div>

      {!isOnCorrectNetwork && (
        <Alert variant="default" className="bg-yellow-500/10 border-yellow-500/20">
          <AlertCircle className="h-4 w-4 text-yellow-500" />
          <AlertTitle>Network Warning</AlertTitle>
          <AlertDescription>
            You&apos;re not on the GenLayer network. Please switch networks in
            MetaMask or try reconnecting.
          </AlertDescription>
        </Alert>
      )}

      {connectionError && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{connectionError}</AlertDescription>
        </Alert>
      )}

      <div className="pt-2 space-y-3">
        <Button
          onClick={handleSwitchAccount}
          variant="outline"
          className="w-full"
          disabled={isSwitching || isLoading}
        >
          <User className="w-4 h-4 mr-2" />
          {isSwitching ? "Switching..." : "Switch Account"}
        </Button>

        <Button
          onClick={() => disconnectWallet()}
          className="w-full text-destructive hover:text-destructive"
          variant="outline"
          disabled={isSwitching || isLoading}
        >
          <LogOut className="w-4 h-4 mr-2" />
          Disconnect Wallet
        </Button>
      </div>
    </div>
  );
}
