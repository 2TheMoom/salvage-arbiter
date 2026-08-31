"use client";

import { useState, useEffect } from "react";
import { Plus, Loader2, Wallet, Link as LinkIcon, FileText } from "lucide-react";
import { useSubmitClaim } from "@/lib/hooks/useRecoveryArbiter";
import type { FeePresetLevel } from "@/lib/genlayer/fees";
import { useWallet } from "@/lib/genlayer/wallet";
import { error } from "@/lib/utils/toast";
import { Button } from "./ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "./ui/dialog";
import { Input } from "./ui/input";
import { Label } from "./ui/label";

export function SubmitClaimModal() {
  const { isConnected, address, isLoading } = useWallet();
  const { submitClaim, isSubmitting, isSuccess } = useSubmitClaim();

  const [isOpen, setIsOpen] = useState(false);
  const [drainedWallet, setDrainedWallet] = useState("");
  const [evidenceUrl, setEvidenceUrl] = useState("");
  const [statement, setStatement] = useState("");
  const [feePresetLevel, setFeePresetLevel] = useState<FeePresetLevel>("standard");

  const [errors, setErrors] = useState({
    drainedWallet: "",
    evidenceUrl: "",
    statement: "",
  });

  // Auto-close modal when wallet disconnects, unless a submission is in flight
  useEffect(() => {
    if (!isConnected && isOpen && !isSubmitting) {
      setIsOpen(false);
    }
  }, [isConnected, isOpen, isSubmitting]);

  const validateForm = (): boolean => {
    const newErrors = { drainedWallet: "", evidenceUrl: "", statement: "" };

    if (!drainedWallet.trim()) {
      newErrors.drainedWallet = "Drained wallet address is required";
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

    submitClaim({
      drainedWallet: drainedWallet.trim(),
      evidenceUrl: evidenceUrl.trim(),
      statement: statement.trim(),
      feePresetLevel,
    });
  };

  const resetForm = () => {
    setDrainedWallet("");
    setEvidenceUrl("");
    setStatement("");
    setErrors({ drainedWallet: "", evidenceUrl: "", statement: "" });
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
          <Plus className="w-4 h-4 mr-2" />
          Submit Claim
        </Button>
      </DialogTrigger>
      <DialogContent className="brand-card border-2 sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle className="text-2xl font-bold">Submit Recovery Claim</DialogTitle>
          <DialogDescription>
            Assert ownership of a drained wallet and point to public evidence.
            Validators will independently review it and reach an AI-adjudicated verdict.
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
              placeholder="0x... (the compromised wallet, any chain)"
              value={drainedWallet}
              onChange={(e) => {
                setDrainedWallet(e.target.value);
                setErrors({ ...errors, drainedWallet: "" });
              }}
              className={errors.drainedWallet ? "border-destructive" : ""}
            />
            {errors.drainedWallet && (
              <p className="text-xs text-destructive">{errors.drainedWallet}</p>
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
              placeholder="Explain why you're the rightful owner of this wallet..."
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
            <Label>Fee Preset</Label>
            <div className="grid grid-cols-3 gap-2">
              {([
                { value: "low", label: "Low", detail: "No appeals" },
                { value: "standard", label: "Standard", detail: "1 appeal" },
                { value: "high", label: "High", detail: "2 appeals" },
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
          <div className="flex gap-3 pt-4">
            <Button
              type="button"
              variant="secondary"
              className="flex-1"
              onClick={() => setIsOpen(false)}
              disabled={isSubmitting}
            >
              Cancel
            </Button>
            <Button type="submit" variant="gradient" className="flex-1" disabled={isSubmitting}>
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
        </form>
      </DialogContent>
    </Dialog>
  );
}
