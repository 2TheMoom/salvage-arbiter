"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import RecoveryReleaseVault, { type VaultWriteName } from "../contracts/RecoveryReleaseVault";
import { getStudioUrl, getVaultAddress } from "../genlayer/client";
import { useWallet } from "../genlayer/wallet";
import { error as toastError, success } from "../utils/toast";
import type { VaultAccounting, VaultRelease } from "../contracts/types";

/** The vault client, or null when NEXT_PUBLIC_VAULT_ADDRESS is not set (the Vault tab then stays hidden). */
export function useVaultContract(): RecoveryReleaseVault | null {
  const { address } = useWallet();
  const vaultAddress = getVaultAddress();
  const rpcUrl = getStudioUrl();
  return useMemo(
    () => (vaultAddress ? new RecoveryReleaseVault(vaultAddress, address, rpcUrl) : null),
    [vaultAddress, address, rpcUrl],
  );
}

const POLL_MS = 20_000;

export function useVaultRelease(claimId: string | null) {
  const vault = useVaultContract();
  return useQuery<VaultRelease, Error>({
    queryKey: ["vaultRelease", claimId],
    queryFn: () => vault!.getRelease(claimId!),
    enabled: !!vault && !!claimId,
    staleTime: 2000,
    refetchInterval: POLL_MS,
    refetchOnWindowFocus: true,
  });
}

export function useVaultDeposit(claimId: string | null) {
  const vault = useVaultContract();
  return useQuery<bigint, Error>({
    queryKey: ["vaultDeposit", claimId],
    queryFn: () => vault!.getDeposit(claimId!),
    enabled: !!vault && !!claimId,
    staleTime: 2000,
    refetchInterval: POLL_MS,
    refetchOnWindowFocus: true,
  });
}

/** The connected wallet's own deposit on a claim, and any refund already recorded for it but not yet paid. */
export function useMyVaultPosition(claimId: string | null) {
  const vault = useVaultContract();
  const { address } = useWallet();
  return useQuery<{ amount: bigint; pendingRefund: bigint }, Error>({
    queryKey: ["vaultPosition", claimId, address],
    queryFn: async () => {
      const [amount, pendingRefund] = await Promise.all([
        vault!.getDepositorAmount(claimId!, address!),
        vault!.getPendingRefund(claimId!, address!),
      ]);
      return { amount, pendingRefund };
    },
    enabled: !!vault && !!claimId && !!address,
    staleTime: 2000,
    refetchInterval: POLL_MS,
    refetchOnWindowFocus: true,
  });
}

export function useVaultAccounting() {
  const vault = useVaultContract();
  return useQuery<VaultAccounting, Error>({
    queryKey: ["vaultAccounting"],
    queryFn: () => vault!.getAccounting(),
    enabled: !!vault,
    staleTime: 2000,
    refetchInterval: POLL_MS,
    refetchOnWindowFocus: true,
  });
}

const DONE_TEXT: Record<VaultWriteName, { title: string; description: string }> = {
  deposit_for_claim: { title: "Deposit recorded", description: "Your GEN is now held for this claim." },
  queue_release: { title: "Release queued", description: "The one-hour challenge window has started." },
  cancel_queue: { title: "Queue cancelled", description: "The claim no longer looked the way it did when it was queued." },
  release: { title: "Payout decision recorded", description: "No money has moved yet. The next step pays the claimant." },
  settle: { title: "Payout sent", description: "It lands once the transaction finalizes, about 30 minutes." },
  refund: { title: "Refund recorded", description: "No money has moved yet. The next step pays it back to you." },
  settle_refund: { title: "Refund sent", description: "It lands once the transaction finalizes, about 30 minutes." },
};

/** One write at a time. Tracks which action is running and its transaction hash, then refreshes everything the vault shows. */
export function useVaultAction() {
  const vault = useVaultContract();
  const { address } = useWallet();
  const queryClient = useQueryClient();
  const [activeFn, setActiveFn] = useState<VaultWriteName | null>(null);
  const [pendingTxHash, setPendingTxHash] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: async (input: { fn: VaultWriteName; args: unknown[]; value?: bigint }) => {
      if (!vault) throw new Error("The vault is not configured.");
      if (!address) throw new Error("Connect your wallet first.");
      setActiveFn(input.fn);
      setPendingTxHash(null);
      await vault.write(input.fn, input.args, input.value ?? BigInt(0), setPendingTxHash);
      return input.fn;
    },
    onSuccess: (fn) => {
      setActiveFn(null);
      const done = DONE_TEXT[fn];
      success(done.title, { description: done.description });
      for (const key of ["vaultRelease", "vaultDeposit", "vaultPosition", "vaultAccounting"]) {
        queryClient.invalidateQueries({ queryKey: [key] });
      }
    },
    onError: (err: any) => {
      setActiveFn(null);
      toastError("That did not go through", { description: err?.message || "Please try again." });
    },
  });

  return {
    run: mutation.mutate,
    isRunning: mutation.isPending,
    activeFn,
    pendingTxHash,
  };
}
