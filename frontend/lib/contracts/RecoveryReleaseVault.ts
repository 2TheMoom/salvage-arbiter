import { createClient } from "genlayer-js";
import { getEthereumProvider } from "../genlayer/client";
import { getGenLayerChain } from "../genlayer/chains";
import type { VaultAccounting, VaultPhase, VaultRelease } from "./types";

/** genlayer-js decodes dicts as JS Map instances or plain objects depending on the call; flatten both. */
function toPlain(raw: any): Record<string, any> {
  const entries = raw instanceof Map ? Array.from(raw.entries()) : Object.entries(raw ?? {});
  const obj: Record<string, any> = {};
  for (const [key, value] of entries) obj[key] = value && typeof value === "object" && "as_hex" in value ? value.as_hex : value;
  return obj;
}

const big = (v: unknown): bigint => {
  try {
    return BigInt((v as any) ?? 0);
  } catch {
    return BigInt(0);
  }
};

const PHASES: VaultPhase[] = ["open", "queued", "decided", "settled"];

/**
 * The contract's own refusal text. The node returns it as raw bytes inside the error message, so pull out the readable
 * sentence. Returns null when the error carries no contract refusal (for example a network failure).
 */
export function refusalReason(err: unknown): string | null {
  const text = String((err as any)?.message ?? err);
  const m = text.match(/ReturnData:\[\]uint8\{([^}]*)\}/);
  if (!m) return null;
  const bytes = m[1].split(",").map((s) => parseInt(s.trim(), 16)).filter((n) => !Number.isNaN(n));
  const runs: string[] = [];
  let cur = "";
  for (const b of bytes) {
    if (b >= 32 && b < 127) cur += String.fromCharCode(b);
    else {
      if (cur.length >= 10) runs.push(cur);
      cur = "";
    }
  }
  if (cur.length >= 10) runs.push(cur);
  return runs.find((r) => r.includes(" ")) ?? null;
}

/** What each way a transaction can end without a result means, in plain words. */
const FAILED: Record<string, string> = {
  LEADER_TIMEOUT: "The validators' leader did not answer in time. Nothing was changed on-chain. Try again in a moment.",
  VALIDATORS_TIMEOUT: "The validators did not finish in time. Nothing was changed on-chain. Try again in a moment.",
  UNDETERMINED: "The validators could not agree this time, so nothing was changed. Try again.",
  CANCELED: "This transaction was cancelled. Nothing was changed.",
};

export type VaultWriteName =
  | "deposit_for_claim"
  | "queue_release"
  | "cancel_queue"
  | "release"
  | "settle"
  | "refund"
  | "settle_refund";

/**
 * RecoveryReleaseVault client. Every write is checked first with a simulation, so a refusal shows the contract's own
 * reason before anything is sent, and the result is read from the transaction itself, not assumed from a hash.
 */
class RecoveryReleaseVault {
  private contractAddress: `0x${string}`;
  private client: any;
  private rpcUrl?: string;

  constructor(contractAddress: string, address?: string | null, rpcUrl?: string) {
    this.contractAddress = contractAddress as `0x${string}`;
    this.rpcUrl = rpcUrl;
    this.client = this.build(address);
  }

  private build(address?: string | null) {
    const config: any = { chain: getGenLayerChain() };
    if (address) {
      config.account = address as `0x${string}`;
      // sign with MetaMask's own provider, not whichever wallet owns window.ethereum (several can be installed)
      const provider = getEthereumProvider();
      if (provider) config.provider = provider;
    }
    if (this.rpcUrl) config.endpoint = this.rpcUrl;
    return createClient(config);
  }

  updateAccount(address: string): void {
    this.client = this.build(address);
  }

  private read(functionName: string, args: unknown[] = []): Promise<any> {
    return this.client.readContract({ address: this.contractAddress, functionName, args });
  }

  async getRelease(claimId: string): Promise<VaultRelease> {
    const r = toPlain(await this.read("get_release", [claimId]));
    const phase = PHASES.includes(r.phase) ? (r.phase as VaultPhase) : "open";
    return {
      phase,
      claimant: String(r.claimant ?? ""),
      asset: String(r.asset ?? ""),
      boundAmount: big(r.bound_amount),
      challenges: Number(r.challenges ?? 0),
      queuedAt: Number(r.queued_at ?? 0),
      releaseAt: Number(r.release_at ?? 0),
      pay: big(r.pay),
    };
  }

  async getDeposit(claimId: string): Promise<bigint> {
    return big(await this.read("get_deposit", [claimId]));
  }

  async getDepositorAmount(claimId: string, depositor: string): Promise<bigint> {
    return big(await this.read("get_depositor_amount", [claimId, depositor]));
  }

  async getPendingRefund(claimId: string, depositor: string): Promise<bigint> {
    return big(await this.read("get_pending_refund", [claimId, depositor]));
  }

  async getAccounting(): Promise<VaultAccounting> {
    const a = toPlain(await this.read("get_accounting"));
    return {
      balance: big(a.balance),
      totalReceived: big(a.total_received),
      totalScheduled: big(a.total_scheduled),
      unscheduled: big(a.unscheduled),
      inFlight: big(a.in_flight),
      shortfall: big(a.shortfall),
    };
  }

  /**
   * Sends one write and waits for the network's answer. Throws a plain-language Error when the contract refuses (before
   * anything is sent), when validators time out, or when the transaction finishes with an error.
   */
  async write(
    functionName: VaultWriteName,
    args: unknown[],
    value: bigint = BigInt(0),
    onSubmitted?: (txHash: string) => void,
  ): Promise<string> {
    const request = { address: this.contractAddress, functionName, args, ...(value > BigInt(0) ? { value } : {}) };

    if (typeof this.client.simulateWriteContract === "function") {
      try {
        await this.client.simulateWriteContract(request);
      } catch (error) {
        const reason = refusalReason(error);
        if (reason) throw new Error(reason);
        // no contract reason in the error (simulation unavailable, network blip): fall through and let the real send decide
      }
    }

    let txHash: string;
    try {
      txHash = await this.client.writeContract(request);
    } catch (error) {
      console.error(`Error calling ${functionName}:`, error);
      const msg = String((error as any)?.message ?? "");
      if (/reject|denied|cancel/i.test(msg)) throw new Error("The request was cancelled in your wallet. Nothing was sent.");
      throw new Error("Could not send the transaction. Please try again.");
    }

    onSubmitted?.(txHash);

    const deadline = Date.now() + 10 * 60_000;
    for (;;) {
      let tx: any = null;
      try {
        tx = await this.client.getTransaction({ hash: txHash });
      } catch (error) {
        console.error("Error reading the transaction (will retry):", error);
      }
      const status = String(tx?.statusName ?? "");
      if (status === "ACCEPTED" || status === "FINALIZED") {
        const exec = String(tx?.txExecutionResultName ?? "");
        if (exec && exec !== "FINISHED_WITH_RETURN") {
          throw new Error(`The contract refused this action (${exec}), so nothing changed. Transaction ${txHash}.`);
        }
        return txHash;
      }
      if (FAILED[status]) throw new Error(`${FAILED[status]} Transaction ${txHash}.`);
      if (Date.now() > deadline) {
        throw new Error(`Transaction ${txHash} is still being worked on after 10 minutes. It may still complete: check the explorer before trying again.`);
      }
      await new Promise((r) => setTimeout(r, 5000));
    }
  }
}

export default RecoveryReleaseVault;
