"use client";

import { useState, useEffect } from "react";
import { Scale, Loader2, Link as LinkIcon, FileText } from "lucide-react";
import { useSubmitAppeal } from "@/lib/hooks/useRecoveryArbiter";
import type { FeePresetLevel } from "@/lib/genlayer/fees";
import { getTxExplorerUrl } from "@/lib/genlayer/chains";
import { Button } from "./ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "./ui/dialog";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import type { Claim } from "@/lib/contracts/types";
import { MAX_APPEALS } from "@/lib/contracts/types";

interface AppealModalProps {
  claim: Claim;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function AppealModal({ claim, open, onOpenChange }: AppealModalProps) {
  const { submitAppeal, isAppealing, isSuccess, pendingTxHash, clearPendingTx } = useSubmitAppeal();

  const [evidenceUrl, setEvidenceUrl] = useState("");
  const [statement, setStatement] = useState("");
  const [feePresetLevel, setFeePresetLevel] = useState<FeePresetLevel>("standard");
  const [errors, setErrors] = useState({ evidenceUrl: "", statement: "" });

  const appealsLeft = MAX_APPEALS - claim.appeal_count;

  const resetForm = () => {
    setEvidenceUrl("");
    setStatement("");
    setErrors({ evidenceUrl: "", statement: "" });
    clearPendingTx();
  };

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen && !isAppealing) {
      resetForm();
    }
    onOpenChange(nextOpen);
  };

  useEffect(() => {
    if (isSuccess) {
      resetForm();
      onOpenChange(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isSuccess]);

  const validateForm = (): boolean => {
    const newErrors = { evidenceUrl: "", statement: "" };

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
      newErrors.statement = "Please explain what's new or different";
    }

    setErrors(newErrors);
    return !Object.values(newErrors).some((e) => e !== "");
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!validateForm()) return;

    submitAppeal({
      claimId: claim.id,
      evidenceUrl: evidenceUrl.trim(),
      statement: statement.trim(),
      feePresetLevel,
    });
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="brand-card border-2 sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle className="text-2xl font-bold flex items-center gap-2">
            <Scale className="w-5 h-5 text-accent" />
            Appeal This Claim
          </DialogTitle>
          <DialogDescription>
            Submit stronger or different evidence and validators will reconsider your
            claim from scratch. {appealsLeft} appeal{appealsLeft === 1 ? "" : "s"} left
            for this claim.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-6 mt-4">
          <div className="brand-card p-3 space-y-1">
            <p className="text-xs text-muted-foreground">Previous verdict</p>
            <p className="text-sm font-semibold capitalize">{claim.status}</p>
            <p className="text-xs text-muted-foreground">{claim.verdict_reasoning}</p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="appealEvidenceUrl" className="flex items-center gap-2">
              <LinkIcon className="w-4 h-4" />
              New Evidence URL
            </Label>
            <Input
              id="appealEvidenceUrl"
              type="text"
              placeholder="A stronger signed message, social post, or explorer link"
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

          <div className="space-y-2">
            <Label htmlFor="appealStatement" className="flex items-center gap-2">
              <FileText className="w-4 h-4" />
              What's new
            </Label>
            <textarea
              id="appealStatement"
              placeholder="Explain what this evidence shows that the previous submission didn't..."
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
                colliding with this modal's own claim-appeal terminology - this
                fee tier controls GenLayer's network-level validator dispute
                budget, an unrelated protocol concept. */}
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

          <div className="space-y-2 pt-4">
            {isAppealing && (
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
                onClick={() => handleOpenChange(false)}
                disabled={isAppealing}
              >
                Cancel
              </Button>
              <Button type="submit" variant="gradient" className="flex-1" disabled={isAppealing}>
                {isAppealing ? (
                  <>
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    Appealing...
                  </>
                ) : (
                  "Submit Appeal"
                )}
              </Button>
            </div>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
