"use client";

import { useState, useEffect } from "react";
import { Plus, Loader2, Wallet, Link as LinkIcon, FileText, ShieldCheck, Copy, Check, AlertTriangle } from "lucide-react";
import { useSubmitClaim } from "@/lib/hooks/useRecoveryArbiter";
import type { FeePresetLevel } from "@/lib/genlayer/fees";
import { useWallet } from "@/lib/genlayer/wallet";
import { getTxExplorerUrl } from "@/lib/genlayer/chains";
import {
  buildOwnershipMessage,
  extractEthAddress,
  signOwnershipMessage,
  verifyOwnershipSignature,
} from "@/lib/genlayer/signing";
import { error } from "@/lib/utils/toast";
import { Button } from "./ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "./ui/dialog";
import { Input } from "./ui/input";
import { Label } from "./ui/label";

export function SubmitClaimModal() {
  const { isConnected, address, isLoading } = useWallet();
  const { submitClaim, isSubmitting, isSuccess, pendingTxHash, clearPendingTx } = useSubmitClaim();

  const [isOpen, setIsOpen] = useState(false);
  const [drainedWallet, setDrainedWallet] = useState("");
  const [evidenceUrl, setEvidenceUrl] = useState("");
  const [statement, setStatement] = useState("");
  const [feePresetLevel, setFeePresetLevel] = useState<FeePresetLevel>("standard");

  // Signature step
  const [signature, setSignature] = useState("");
  const [signedForAddress, setSignedForAddress] = useState<string | null>(null);
  const [isSigning, setIsSigning] = useState(false);
  const [signError, setSignError] = useState("");
  const [copied, setCopied] = useState(false);

  const [errors, setErrors] = useState({
    drainedWallet: "",
    evidenceUrl: "",
    statement: "",
  });

  const walletAddress = extractEthAddress(drainedWallet);
  const message = walletAddress && address ? buildOwnershipMessage(drainedWallet.trim(), address) : "";
  const accountChangedSinceSigning = signature !== "" && signedForAddress !== address;

  // A stale signature (wallet/address changed after signing) can't be submitted
  useEffect(() => {
    if (signature && accountChangedSinceSigning) {
      setSignature("");
      setSignError("Your connected account changed - please sign again.");
    }
  }, [accountChangedSinceSigning, signature]);

  // Auto-close modal when wallet disconnects, unless a submission is in flight
  useEffect(() => {
    if (!isConnected && isOpen && !isSubmitting) {
      setIsOpen(false);
    }
  }, [isConnected, isOpen, isSubmitting]);

  const handleSign = async () => {
    if (!walletAddress || !address) return;
    setIsSigning(true);
    setSignError("");
    try {
      const sig = await signOwnershipMessage(walletAddress, message);
      const verified = await verifyOwnershipSignature(walletAddress, message, sig);
      if (!verified) {
        setSignError(
          "That signature doesn't match this wallet address. Make sure you signed with the drained wallet's own account, not your claiming account."
        );
        return;
      }
      setSignature(sig);
      setSignedForAddress(address);
    } catch (err: any) {
      setSignError(err.message || "Failed to sign message");
    } finally {
      setIsSigning(false);
    }
  };

  const handleCopyMessage = async () => {
    if (!message) return;
    await navigator.clipboard.writeText(message);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const validateForm = (): boolean => {
    const newErrors = { drainedWallet: "", evidenceUrl: "", statement: "" };

    if (!drainedWallet.trim()) {
      newErrors.drainedWallet = "Drained wallet address is required";
    } else if (!walletAddress) {
      newErrors.drainedWallet = "Must be a valid 0x... address (optionally chain-prefixed, e.g. eth:0x...)";
    }

    if (!evidenceUrl.trim()) {
      newErrors.evidenceUrl = "A public evidence URL is required";
    } else {
      try {
        new URL(evidenceUrl.trim());
      } catch {
        newErrors.evidenceUrl = "Must be a valid URL";
      }
    }

    if (!statement.trim()) {
      newErrors.statement = "Please explain your claim";
    }

    setErrors(newErrors);
    return !Object.values(newErrors).some((e) => e !== "");
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!isConnected || !address) {
      error("Please connect your wallet first");
      return;
    }

    if (!validateForm()) {
      return;
    }

    if (!signature || accountChangedSinceSigning) {
      error("Please sign the ownership message with the drained wallet first");
      return;
    }

    submitClaim({
      drainedWallet: drainedWallet.trim(),
      evidenceUrl: evidenceUrl.trim(),
      statement: statement.trim(),
      signature,
      feePresetLevel,
    });
  };

  const resetForm = () => {
    setDrainedWallet("");
    setEvidenceUrl("");
    setStatement("");
    setSignature("");
    setSignedForAddress(null);
    setSignError("");
    setErrors({ drainedWallet: "", evidenceUrl: "", statement: "" });
    clearPendingTx();
  };

  const handleOpenChange = (open: boolean) => {
    if (!open && !isSubmitting) {
      resetForm();
    }
    setIsOpen(open);
  };

  // Reset form and close modal on successful submission
  useEffect(() => {
    if (isSuccess) {
      resetForm();
      setIsOpen(false);
    }
  }, [isSuccess]);

  return (
    <Dialog open={isOpen} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button variant="gradient" disabled={!isConnected || !address || isLoading}>
          <Plus className="w-4 h-4 sm:mr-2" />
          <span className="hidden sm:inline">Submit Claim</span>
        </Button>
      </DialogTrigger>
      <DialogContent className="brand-card border-2 sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle className="text-2xl font-bold">Submit Recovery Claim</DialogTitle>
          <DialogDescription>
            Prove control of a drained wallet with a signature, point to supporting
            evidence, and validators will independently reach an AI-adjudicated verdict.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-6 mt-4">
          {/* Drained Wallet */}
          <div className="space-y-2">
            <Label htmlFor="drainedWallet" className="flex items-center gap-2">
              <Wallet className="w-4 h-4 !text-white" />
              Drained Wallet Address
            </Label>
            <Input
              id="drainedWallet"
              type="text"
              placeholder="0x... (the compromised wallet; eth: prefix optional)"
              value={drainedWallet}
              onChange={(e) => {
                setDrainedWallet(e.target.value);
                setErrors({ ...errors, drainedWallet: "" });
                setSignature("");
                setSignError("");
              }}
              className={errors.drainedWallet ? "border-destructive" : ""}
            />
            {errors.drainedWallet && (
              <p className="text-xs text-destructive">{errors.drainedWallet}</p>
            )}
          </div>

          {/* Ownership signature */}
          <div className="space-y-2">
            <Label className="flex items-center gap-2">
              <ShieldCheck className="w-4 h-4" />
              Prove Ownership
            </Label>

            {!walletAddress ? (
              <p className="text-xs text-muted-foreground">
                Enter a valid drained wallet address above to generate a message to sign.
              </p>
            ) : signature && !accountChangedSinceSigning ? (
              <div className="flex items-center gap-2 rounded-md border border-green-500/30 bg-green-500/10 px-3 py-2 text-sm text-green-400">
                <Check className="w-4 h-4 shrink-0" />
                Ownership verified via signature
              </div>
            ) : (
              <div className="space-y-2">
                <div className="rounded-md border border-white/10 bg-muted/10 p-3">
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-xs font-mono break-all text-muted-foreground">{message}</p>
                    <button
                      type="button"
                      onClick={handleCopyMessage}
                      className="shrink-0 text-muted-foreground hover:text-accent"
                      aria-label="Copy message"
                    >
                      {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                    </button>
                  </div>
                </div>
                <p className="text-xs text-muted-foreground">
                  Switch MetaMask to the drained wallet&apos;s account, then sign this exact
                  message. You&apos;ll switch back to your normal account before submitting.
                </p>
                <Button
                  type="button"
                  variant="outline"
                  className="w-full"
                  onClick={handleSign}
                  disabled={isSigning}
                >
                  {isSigning ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      Waiting for signature...
                    </>
                  ) : (
                    "Sign with MetaMask"
                  )}
                </Button>
                {signError && (
                  <p className="text-xs text-destructive flex items-start gap-1">
                    <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                    {signError}
                  </p>
                )}
              </div>
            )}
          </div>

          {/* Evidence URL */}
          <div className="space-y-2">
            <Label htmlFor="evidenceUrl" className="flex items-center gap-2">
              <LinkIcon className="w-4 h-4" />
              Public Evidence URL
            </Label>
            <Input
              id="evidenceUrl"
              type="text"
              placeholder="A signed message, social post, or explorer link"
              value={evidenceUrl}
              onChange={(e) => {
                setEvidenceUrl(e.target.value);
                setErrors({ ...errors, evidenceUrl: "" });
              }}
              className={errors.evidenceUrl ? "border-destructive" : ""}
            />
            {errors.evidenceUrl && (
              <p className="text-xs text-destructive">{errors.evidenceUrl}</p>
            )}
          </div>

          {/* Statement */}
          <div className="space-y-2">
            <Label htmlFor="statement" className="flex items-center gap-2">
              <FileText className="w-4 h-4" />
              Your Statement
            </Label>
            <textarea
              id="statement"
              placeholder="Explain the circumstances of the drain and your recovery request..."
              value={statement}
              onChange={(e) => {
                setStatement(e.target.value);
                setErrors({ ...errors, statement: "" });
              }}
              rows={4}
              className={`w-full rounded-md border bg-transparent px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent ${
                errors.statement ? "border-destructive" : "border-white/10"
              }`}
            />
            {errors.statement && (
              <p className="text-xs text-destructive">{errors.statement}</p>
            )}
          </div>

          <div className="space-y-3">
            {/* Labeled "dispute rounds" (not "appeals") here specifically to avoid
                colliding with the claim-appeal feature - this fee tier controls
                GenLayer's network-level validator dispute budget, an unrelated
                protocol concept. */}
            <Label>Network Fee Tier</Label>
            <div className="grid grid-cols-3 gap-2">
              {([
                { value: "low", label: "Low", detail: "No extra rounds" },
                { value: "standard", label: "Standard", detail: "+1 dispute round" },
                { value: "high", label: "High", detail: "+2 dispute rounds" },
              ] as const).map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setFeePresetLevel(option.value)}
                  className={`rounded-md border px-3 py-2 text-left transition-all ${
                    feePresetLevel === option.value
                      ? "border-accent bg-accent/20 text-accent"
                      : "border-white/10 hover:border-white/20"
                  }`}
                >
                  <div className="text-sm font-semibold">{option.label}</div>
                  <div className="mt-0.5 text-xs text-muted-foreground">{option.detail}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Submit Button */}
          <div className="space-y-2 pt-4">
            {isSubmitting && (
              <div className="flex items-center justify-between gap-2 rounded-md border border-white/10 bg-muted/10 px-3 py-2 text-xs text-muted-foreground">
                {pendingTxHash ? (
                  <>
                    <span>Transaction submitted - waiting for validator confirmation...</span>
                    <a
                      href={getTxExplorerUrl(pendingTxHash)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="shrink-0 font-semibold text-accent hover:underline"
                    >
                      View on explorer
                    </a>
                  </>
                ) : (
                  <span>Preparing transaction...</span>
                )}
              </div>
            )}
            <div className="flex gap-3">
              <Button
                type="button"
                variant="secondary"
                className="flex-1"
                onClick={() => setIsOpen(false)}
                disabled={isSubmitting}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                variant="gradient"
                className="flex-1"
                disabled={isSubmitting || !signature || accountChangedSinceSigning}
              >
                {isSubmitting ? (
                  <>
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    Submitting...
                  </>
                ) : (
                  "Submit Claim"
                )}
              </Button>
            </div>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
