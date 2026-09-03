"use client";

import { recoverMessageAddress } from "viem";
import { getEthereumProvider } from "./client";

/**
 * Strips an optional chain prefix (e.g. "eth:") and "0x", mirroring the
 * contract's _extract_address_hex. Returns null if what's left isn't a
 * plausible 20-byte address, since personal_sign needs a real "0x..."
 * address, not a chain-prefixed wallet string like "eth:0x...".
 */
export function extractEthAddress(wallet: string): `0x${string}` | null {
  let w = wallet.trim().toLowerCase();
  if (w.includes(":")) {
    w = w.split(":", 2)[1] ?? "";
  }
  if (w.startsWith("0x")) {
    w = w.slice(2);
  }
  if (!/^[0-9a-f]{40}$/.test(w)) {
    return null;
  }
  return `0x${w}`;
}

/**
 * Must match RecoveryArbiter._ownership_message exactly - the contract
 * reconstructs this same string server-side (validator-side) to verify the
 * signature, so any drift here breaks every submission.
 */
export function buildOwnershipMessage(drainedWallet: string, claimantAddress: string): string {
  return `I authorize ${claimantAddress} to submit a Salvage Arbiter recovery claim on behalf of ${drainedWallet}.`;
}

/**
 * Asks MetaMask to sign the ownership message with the drained wallet's key.
 * MetaMask will sign with `drainedWallet` if it's among the site's connected
 * accounts (regardless of which account is currently "active"); otherwise it
 * throws, typically because that address isn't imported/connected yet.
 */
export async function signOwnershipMessage(
  drainedWallet: string,
  message: string
): Promise<string> {
  const provider = getEthereumProvider();
  if (!provider) {
    throw new Error("MetaMask is not installed");
  }

  try {
    const signature = await provider.request({
      method: "personal_sign",
      params: [message, drainedWallet],
    });
    return signature as string;
  } catch (err: any) {
    if (err.code === 4001) {
      throw new Error("Signature request rejected");
    }
    throw new Error(
      err.message ||
        "Failed to sign with that address. Make sure it's imported and connected in MetaMask."
    );
  }
}

/**
 * Client-side sanity check before spending gas: does this signature actually
 * recover to the drained wallet address? Uses recoverMessageAddress (pure
 * ECDSA recovery, no network call) rather than viem's verifyMessage, which
 * can also attempt an EIP-1271 smart-contract-wallet check over RPC - the
 * contract itself only ever does raw ecrecover, so this must match that
 * exactly rather than being "more lenient" than the real, authoritative
 * check on-chain.
 */
export async function verifyOwnershipSignature(
  drainedWallet: string,
  message: string,
  signature: string
): Promise<boolean> {
  try {
    const recovered = await recoverMessageAddress({
      message,
      signature: signature as `0x${string}`,
    });
    return recovered.toLowerCase() === drainedWallet.toLowerCase();
  } catch {
    return false;
  }
}
