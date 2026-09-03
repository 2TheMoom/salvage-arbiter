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
