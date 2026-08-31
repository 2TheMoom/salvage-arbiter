"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import RecoveryArbiter from "../contracts/RecoveryArbiter";
import { getContractAddress, getStudioUrl } from "../genlayer/client";
import type { FeePresetLevel } from "../genlayer/fees";
import { useWallet } from "../genlayer/wallet";
import { success, error, configError } from "../utils/toast";
import type { Claim } from "../contracts/types";

/**
 * Hook to get the RecoveryArbiter contract instance.
 *
 * Returns null if contract address is not configured. Read-only operations
 * work without a connected wallet; write operations (submitClaim, adjudicate)
 * require one.
 */
export function useRecoveryArbiterContract(): RecoveryArbiter | null {
  const { address } = useWallet();
  const contractAddress = getContractAddress();
  const rpcUrl = getStudioUrl();

  const contract = useMemo(() => {
    if (!contractAddress) {
      configError(
        "Setup Required",
        "Contract address not configured. Please set NEXT_PUBLIC_CONTRACT_ADDRESS in your .env file.",
        {
          label: "Setup Guide",
          onClick: () => window.open("/docs/setup", "_blank"),
        }
      );
      return null;
    }

    return new RecoveryArbiter(contractAddress, address, rpcUrl);
  }, [contractAddress, address, rpcUrl]);

  return contract;
}

/**
 * Hook to fetch all claims. Refetches on window focus and after mutations.
 */
export function useClaims() {
  const contract = useRecoveryArbiterContract();

  return useQuery<Claim[], Error>({
    queryKey: ["claims"],
    queryFn: () => {
      if (!contract) {
        return Promise.resolve([]);
      }
      return contract.getAllClaims();
    },
    refetchOnWindowFocus: true,
    staleTime: 2000,
    enabled: !!contract,
  });
}

/**
 * Hook to fetch claims submitted by a specific address
 */
export function useClaimsByAddress(address: string | null) {
  const contract = useRecoveryArbiterContract();

  return useQuery<Claim[], Error>({
    queryKey: ["claimsByAddress", address],
    queryFn: () => {
      if (!contract) {
        return Promise.resolve([]);
      }
      return contract.getClaimsByAddress(address);
    },
    refetchOnWindowFocus: true,
    enabled: !!address && !!contract,
    staleTime: 2000,
  });
}

/**
 * Hook to submit a new fund-recovery claim
 */
export function useSubmitClaim() {
  const contract = useRecoveryArbiterContract();
  const { address } = useWallet();
  const queryClient = useQueryClient();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const mutation = useMutation({
    mutationFn: async ({
      drainedWallet,
      evidenceUrl,
      statement,
      feePresetLevel,
    }: {
      drainedWallet: string;
      evidenceUrl: string;
      statement: string;
      feePresetLevel?: FeePresetLevel;
    }) => {
      if (!contract) {
        throw new Error("Contract not configured. Please set NEXT_PUBLIC_CONTRACT_ADDRESS in your .env file.");
      }
      if (!address) {
        throw new Error("Wallet not connected. Please connect your wallet to submit a claim.");
      }
      setIsSubmitting(true);
      const feePreset = await contract.estimateSubmitClaimFees(
        drainedWallet,
        evidenceUrl,
        statement,
        feePresetLevel ?? "standard"
      );
      return contract.submitClaim(drainedWallet, evidenceUrl, statement, feePreset);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["claims"] });
      queryClient.invalidateQueries({ queryKey: ["claimsByAddress"] });
      setIsSubmitting(false);
      success("Claim submitted successfully!", {
        description: "Your recovery claim has been recorded on-chain.",
      });
    },
    onError: (err: any) => {
      console.error("Error submitting claim:", err);
      setIsSubmitting(false);
      error("Failed to submit claim", {
        description: err?.message || "Please try again.",
      });
    },
  });

  return {
    ...mutation,
    isSubmitting,
    submitClaim: mutation.mutate,
    submitClaimAsync: mutation.mutateAsync,
  };
}

/**
 * Hook to trigger AI adjudication of a pending claim
 */
export function useAdjudicate() {
  const contract = useRecoveryArbiterContract();
  const { address } = useWallet();
  const queryClient = useQueryClient();
  const [isAdjudicating, setIsAdjudicating] = useState(false);
  const [adjudicatingClaimId, setAdjudicatingClaimId] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: async (claimId: string) => {
      if (!contract) {
        throw new Error("Contract not configured. Please set NEXT_PUBLIC_CONTRACT_ADDRESS in your .env file.");
      }
      if (!address) {
        throw new Error("Wallet not connected. Please connect your wallet to adjudicate a claim.");
      }
      setIsAdjudicating(true);
      setAdjudicatingClaimId(claimId);
      return contract.adjudicate(claimId);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["claims"] });
      queryClient.invalidateQueries({ queryKey: ["claimsByAddress"] });
      setIsAdjudicating(false);
      setAdjudicatingClaimId(null);
      success("Claim adjudicated!", {
        description: "Validators reached a verdict on this claim.",
      });
    },
    onError: (err: any) => {
      console.error("Error adjudicating claim:", err);
      setIsAdjudicating(false);
      setAdjudicatingClaimId(null);
      error("Failed to adjudicate claim", {
        description: err?.message || "Please try again.",
      });
    },
  });

  return {
    ...mutation,
    isAdjudicating,
    adjudicatingClaimId,
    adjudicate: mutation.mutate,
    adjudicateAsync: mutation.mutateAsync,
  };
}
