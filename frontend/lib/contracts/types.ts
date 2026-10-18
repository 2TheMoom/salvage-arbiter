/**
 * TypeScript types for the GenLayer RecoveryArbiter contract
 */

export type ClaimStatus = "pending" | "approved" | "denied" | "insufficient";

export const MAX_APPEALS = 3;

export interface Claim {
  id: string;
  claimant: string;
  drained_wallet: string;
  evidence_url: string;
  statement: string;
  signature: string;
  drain_tx_hash: string;
  status: ClaimStatus;
  verdict_confidence: number;
  verdict_reasoning: string;
  appeal_count: number;
}

export interface TransactionReceipt {
  status: string;
  hash: string;
  blockNumber?: number;
  [key: string]: any;
}

export type VaultPhase = "open" | "queued" | "decided" | "settled";

/** The vault's challenge window, in seconds. Mirrors CHALLENGE_WINDOW in contracts/recovery_release_vault.py. */
export const VAULT_CHALLENGE_WINDOW_SECONDS = 3600;

export interface VaultRelease {
  phase: VaultPhase;
  claimant: string;
  asset: string;
  boundAmount: bigint;
  challenges: number;
  queuedAt: number;
  releaseAt: number;
  pay: bigint;
}

export interface VaultAccounting {
  balance: bigint;
  totalReceived: bigint;
  totalScheduled: bigint;
  unscheduled: bigint;
  inFlight: bigint;
  shortfall: bigint;
}
