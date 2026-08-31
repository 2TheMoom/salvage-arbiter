import { createClient } from "genlayer-js";
import { getGenLayerChain } from "../genlayer/chains";
import type { Claim } from "./types";
import {
  estimateWriteFeePreset,
  feePresetToTransactionFees,
  type FeePresetEstimate,
  type FeePresetLevel,
} from "../genlayer/fees";

/**
 * genlayer-js decodes Python dataclasses (and dicts/TreeMaps) as JS Map
 * instances, keyed by field/dict-key name. This flattens one level of that
 * into a plain object, and normalizes Address-typed fields (like
 * `claimant`) to a checksummed hex string.
 */
function decodeClaim(raw: any): Claim {
  const entries = raw instanceof Map ? Array.from(raw.entries()) : Object.entries(raw ?? {});
  const obj: Record<string, any> = {};
  for (const [key, value] of entries) {
    obj[key] = value && typeof value === "object" && "as_hex" in value ? value.as_hex : value;
  }
  return {
    id: String(obj.id ?? ""),
    claimant: String(obj.claimant ?? ""),
    drained_wallet: String(obj.drained_wallet ?? ""),
    evidence_url: String(obj.evidence_url ?? ""),
    statement: String(obj.statement ?? ""),
    status: (obj.status ?? "pending") as Claim["status"],
    verdict_confidence: Number(obj.verdict_confidence ?? 0),
    verdict_reasoning: String(obj.verdict_reasoning ?? ""),
    appeal_count: Number(obj.appeal_count ?? 0),
  };
}

/**
 * RecoveryArbiter contract class for interacting with the GenLayer
 * fund-recovery-claim arbiter contract.
 */
class RecoveryArbiter {
  private contractAddress: `0x${string}`;
  private client: any;
  private rpcUrl?: string;

  constructor(contractAddress: string, address?: string | null, rpcUrl?: string) {
    this.contractAddress = contractAddress as `0x${string}`;
    this.rpcUrl = rpcUrl;

    const config: any = {
      chain: getGenLayerChain(),
    };

    if (address) {
      config.account = address as `0x${string}`;
    }

    if (rpcUrl) {
      config.endpoint = rpcUrl;
    }

    this.client = createClient(config);
  }

  /**
   * Update the address used for transactions
   */
  updateAccount(address: string): void {
    const config: any = {
      chain: getGenLayerChain(),
      account: address as `0x${string}`,
    };

    if (this.rpcUrl) {
      config.endpoint = this.rpcUrl;
    }

    this.client = createClient(config);
  }

  async estimateSubmitClaimFees(
    drainedWallet: string,
    evidenceUrl: string,
    statement: string,
    level: FeePresetLevel = "standard"
  ): Promise<FeePresetEstimate | undefined> {
    return estimateWriteFeePreset(
      this.client,
      {
        address: this.contractAddress,
        functionName: "submit_claim",
        args: [drainedWallet, evidenceUrl, statement],
      },
      level,
    );
  }

  async estimateAdjudicateFees(
    claimId: string,
    level: FeePresetLevel = "standard"
  ): Promise<FeePresetEstimate | undefined> {
    return estimateWriteFeePreset(
      this.client,
      {
        address: this.contractAddress,
        functionName: "adjudicate",
        args: [claimId],
      },
      level,
    );
  }

  async estimateSubmitAppealFees(
    claimId: string,
    evidenceUrl: string,
    statement: string,
    level: FeePresetLevel = "standard"
  ): Promise<FeePresetEstimate | undefined> {
    return estimateWriteFeePreset(
      this.client,
      {
        address: this.contractAddress,
        functionName: "submit_appeal",
        args: [claimId, evidenceUrl, statement],
      },
      level,
    );
  }

  /**
   * Get every claim registered on the contract
   */
  async getAllClaims(): Promise<Claim[]> {
    try {
      const result: any = await this.client.readContract({
        address: this.contractAddress,
        functionName: "get_all_claims",
        args: [],
      });

      // genlayer-js decodes a dict-returning view as a plain JS object keyed
      // by dict key (verified against the live Bradbury deployment), not a
      // Map — handle both defensively in case that changes across versions.
      if (result instanceof Map) {
        return Array.from(result.values()).map(decodeClaim);
      }
      if (result && typeof result === "object") {
        return Object.values(result).map(decodeClaim);
      }

      return [];
    } catch (error) {
      console.error("Error fetching claims:", error);
      throw new Error("Failed to fetch claims from contract");
    }
  }

  /**
   * Get a single claim by its ID
   */
  async getClaim(claimId: string): Promise<Claim | null> {
    try {
      const result = await this.client.readContract({
        address: this.contractAddress,
        functionName: "get_claim",
        args: [claimId],
      });

      return decodeClaim(result);
    } catch (error) {
      console.error("Error fetching claim:", error);
      return null;
    }
  }

  /**
   * Get all claims submitted by a given address
   */
  async getClaimsByAddress(address: string | null): Promise<Claim[]> {
    if (!address) {
      return [];
    }

    try {
      const result: any = await this.client.readContract({
        address: this.contractAddress,
        functionName: "get_claims_by_address",
        args: [address],
      });

      if (Array.isArray(result)) {
        return result.map(decodeClaim);
      }

      return [];
    } catch (error) {
      console.error("Error fetching claims by address:", error);
      return [];
    }
  }

  /**
   * Submit a new fund-recovery claim
   */
  async submitClaim(
    drainedWallet: string,
    evidenceUrl: string,
    statement: string,
    feePreset?: FeePresetEstimate
  ): Promise<string> {
    try {
      const fees = feePresetToTransactionFees(feePreset);
      const txHash = await this.client.writeContract({
        address: this.contractAddress,
        functionName: "submit_claim",
        args: [drainedWallet, evidenceUrl, statement],
        value: BigInt(0),
        ...(fees ? { fees } : {}),
      });

      await this.client.waitForTransactionReceipt({
        hash: txHash,
        status: "ACCEPTED" as any,
        retries: 24,
        interval: 5000,
      });

      return txHash;
    } catch (error) {
      console.error("Error submitting claim:", error);
      throw new Error("Failed to submit claim");
    }
  }

  /**
   * Trigger AI adjudication of a pending claim
   */
  async adjudicate(claimId: string): Promise<string> {
    try {
      const feePreset = await this.estimateAdjudicateFees(claimId);
      const fees = feePresetToTransactionFees(feePreset);
      const txHash = await this.client.writeContract({
        address: this.contractAddress,
        functionName: "adjudicate",
        args: [claimId],
        value: BigInt(0),
        ...(fees ? { fees } : {}),
      });

      await this.client.waitForTransactionReceipt({
        hash: txHash,
        status: "ACCEPTED" as any,
        retries: 24,
        interval: 5000,
      });

      return txHash;
    } catch (error) {
      console.error("Error adjudicating claim:", error);
      throw new Error("Failed to adjudicate claim");
    }
  }

  /**
   * Appeal a denied/insufficient claim with new evidence, then immediately
   * re-trigger adjudication so the claimant only has to take one action.
   * These are two separate on-chain transactions (submit_appeal resets the
   * claim to "pending", adjudicate re-runs the actual AI consensus), chained
   * here for a single-click UX.
   */
  async submitAppeal(
    claimId: string,
    evidenceUrl: string,
    statement: string,
    feePreset?: FeePresetEstimate
  ): Promise<string> {
    try {
      const fees = feePresetToTransactionFees(feePreset);
      const appealTxHash = await this.client.writeContract({
        address: this.contractAddress,
        functionName: "submit_appeal",
        args: [claimId, evidenceUrl, statement],
        value: BigInt(0),
        ...(fees ? { fees } : {}),
      });

      await this.client.waitForTransactionReceipt({
        hash: appealTxHash,
        status: "ACCEPTED" as any,
        retries: 24,
        interval: 5000,
      });

      return this.adjudicate(claimId);
    } catch (error) {
      console.error("Error submitting appeal:", error);
      throw new Error("Failed to submit appeal");
    }
  }
}

export default RecoveryArbiter;
