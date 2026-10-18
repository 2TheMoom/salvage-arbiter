"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Clock, ExternalLink, Loader2 } from "lucide-react";
import { Navbar } from "@/components/Navbar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { VaultLanes, type LaneNode } from "@/components/vault/VaultLanes";
import { useClaims } from "@/lib/hooks/useRecoveryArbiter";
import {
  useMyVaultPosition,
  useVaultAccounting,
  useVaultAction,
  useVaultContract,
  useVaultDeposit,
  useVaultRelease,
} from "@/lib/hooks/useVault";
import { useWallet } from "@/lib/genlayer/wallet";
import { getTxExplorerUrl } from "@/lib/genlayer/chains";
import { formatGen, parseGen } from "@/lib/utils/gen";
import { VAULT_CHALLENGE_WINDOW_SECONDS } from "@/lib/contracts/types";
import type { Claim } from "@/lib/contracts/types";

const short = (s: string, head = 10, tail = 6) => (s.length > head + tail + 1 ? `${s.slice(0, head)}…${s.slice(-tail)}` : s);

function clock(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

const STATUS_STYLE: Record<string, string> = {
  approved: "bg-green-500/15 text-green-400 border-green-500/30",
  denied: "bg-red-500/15 text-red-400 border-red-500/30",
  insufficient: "bg-orange-500/15 text-orange-400 border-orange-500/30",
  pending: "text-yellow-400 border-yellow-500/30",
};

function VaultView() {
  const router = useRouter();
  const params = useSearchParams();
  const vault = useVaultContract();
  const { address, isOnCorrectNetwork } = useWallet();
  const { data: claims, isLoading: claimsLoading } = useClaims();

  const [claimId, setClaimId] = useState<string | null>(params.get("claim"));
  useEffect(() => {
    if (!claimId && claims && claims.length > 0) {
      setClaimId((claims.find((c) => c.status === "approved") ?? claims[0]).id);
    }
  }, [claims, claimId]);

  const claim: Claim | undefined = useMemo(() => claims?.find((c) => c.id === claimId), [claims, claimId]);
  const { data: release } = useVaultRelease(claimId);
  const { data: total } = useVaultDeposit(claimId);
  const { data: mine } = useMyVaultPosition(claimId);
  const { data: accounting } = useVaultAccounting();
  const action = useVaultAction();
  const [amountText, setAmountText] = useState("");

  const phase = release?.phase ?? "open";
  const queued = phase === "queued";

  // a once-a-second clock, only while there is a countdown to show
  const [now, setNow] = useState(() => Math.floor(Date.now() / 1000));
  useEffect(() => {
    if (!queued) return;
    const id = setInterval(() => setNow(Math.floor(Date.now() / 1000)), 1000);
    return () => clearInterval(id);
  }, [queued]);

  if (!vault) {
    return (
      <div className="brand-card p-8 text-center space-y-2">
        <h2 className="text-xl font-bold">Vault not configured</h2>
        <p className="text-sm text-muted-foreground">Set NEXT_PUBLIC_VAULT_ADDRESS to the RecoveryReleaseVault address.</p>
      </div>
    );
  }

  const status = claim?.status ?? "pending";
  const held = total ?? BigInt(0);
  const myAmount = mine?.amount ?? BigInt(0);
  const myPending = mine?.pendingRefund ?? BigInt(0);
  const windowLeft = queued && release ? release.releaseAt - now : 0;
  const windowOver = queued && windowLeft <= 0;
  const refundMode = phase === "open" && (status === "denied" || status === "insufficient");
  const canAct = !!address && isOnCorrectNetwork && !action.isRunning;

  const reads: LaneNode[] = [];
  const money: LaneNode[] = [];
  if (refundMode) {
    reads.push(
      { col: 1, fn: "arbiter verdict", detail: `${status}, the arbiter's latest`, state: "done" },
      myAmount > BigInt(0)
        ? { col: 2, fn: "refund", detail: "Record a refund of your own deposit", state: "active" }
        : { col: 2, fn: "refund", detail: myPending > BigInt(0) ? "Your refund is recorded" : "You have no deposit here", state: myPending > BigInt(0) ? "done" : "todo" },
    );
    money.push(
      { col: 1, fn: "deposit_for_claim", detail: `${formatGen(held)} GEN still held`, state: held > BigInt(0) || myPending > BigInt(0) ? "done" : "todo" },
      { col: 4, fn: "settle_refund", detail: myPending > BigInt(0) ? `Pay ${formatGen(myPending)} GEN back to you` : "Pays a recorded refund, once", state: myPending > BigInt(0) ? "active" : "todo" },
    );
  } else {
    reads.push(
      { col: 1, fn: "arbiter verdict", detail: `Arbiter says ${status}`, state: status === "pending" ? "active" : "done" },
      phase !== "open"
        ? { col: 2, fn: "queue_release", detail: "Read the finalized approval", state: "done" }
        : { col: 2, fn: "queue_release", detail: status === "approved" && held > BigInt(0) ? "Ready: anyone can queue it" : "Needs a finalized approval and a deposit", state: status === "approved" && held > BigInt(0) ? "active" : "todo" },
      queued && !windowOver
        ? { col: 3, fn: "challenge window", detail: "left of 60:00", state: "active", big: clock(windowLeft), progress: 1 - windowLeft / VAULT_CHALLENGE_WINDOW_SECONDS }
        : phase === "open"
          ? { col: 3, fn: "challenge window", detail: "One hour, starts when queued", state: "todo" }
          : { col: 3, fn: "challenge window", detail: "Closed, nobody froze it", state: "done" },
      phase === "decided" || phase === "settled"
        ? { col: 4, fn: "release", detail: "Decision recorded", state: "done" }
        : { col: 4, fn: "release", detail: windowOver ? "Ready: records the decision" : "Checks the claim looks the same", state: windowOver ? "active" : "todo" },
    );
    money.push(
      { col: 1, fn: "deposit_for_claim", detail: held > BigInt(0) || phase === "decided" || phase === "settled" ? `${formatGen(held)} GEN held` : "Nothing deposited yet", state: held > BigInt(0) || phase === "decided" || phase === "settled" ? "done" : "todo" },
      phase === "settled"
        ? { col: 5, fn: "settle", detail: `Paid ${formatGen(release?.pay ?? BigInt(0))} GEN to the claimant`, state: "done" }
        : { col: 5, fn: "settle", detail: phase === "decided" ? `Ready: pays ${formatGen(release?.pay ?? BigInt(0))} GEN once` : "Pays the claimant once", state: phase === "decided" ? "active" : "todo" },
    );
  }

  const send = (fn: Parameters<typeof action.run>[0]["fn"], args: unknown[], value?: bigint) => action.run({ fn, args, value });

  const depositWei = parseGen(amountText);
  const depositOpen = phase === "open" || phase === "queued";

  return (
    <div className="space-y-10">
      {/* claim picker */}
      <section className="flex flex-wrap items-end justify-between gap-6">
        <div className="max-w-2xl space-y-3">
          <span className="text-xs font-semibold uppercase tracking-[0.14em] text-accent">Recovery release vault</span>
          <h1 className="font-[family-name:var(--font-display)] text-4xl md:text-5xl font-medium leading-[1.05] tracking-tight text-balance">
            {refundMode
              ? "Denied, so each depositor takes back their own"
              : "Held until the verdict is final and the window is quiet"}
          </h1>
          <p className="text-muted-foreground max-w-[60ch]">
            {refundMode
              ? "The arbiter denied this claim. Nothing goes to the claimant. Every depositor can reclaim exactly what they put in, and nobody can touch anyone else's share."
              : "GEN deposited for a claim is paid to the claimant only after the arbiter's approval is finalized and nobody has challenged it for one hour."}
          </p>
        </div>
        <div className="min-w-[260px] space-y-2">
          <Label htmlFor="claim-pick" className="text-xs uppercase tracking-widest text-muted-foreground">
            Claim
          </Label>
          <select
            id="claim-pick"
            value={claimId ?? ""}
            disabled={claimsLoading || !claims?.length}
            onChange={(e) => {
              setClaimId(e.target.value);
              router.replace(`/app/vault?claim=${encodeURIComponent(e.target.value)}`);
            }}
            className="w-full rounded-lg border border-white/10 bg-[#17120a] px-3 py-2.5 font-mono text-sm text-foreground"
          >
            {(claims ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                {short(c.drained_wallet, 10, 6)} · {c.status}
              </option>
            ))}
          </select>
          {claim && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span className={`rounded-full border px-2.5 py-0.5 font-semibold ${STATUS_STYLE[claim.status]}`}>{claim.status}</span>
              <span>the arbiter's latest, the vault reads its finalized state</span>
            </div>
          )}
        </div>
      </section>

      {!claim ? (
        <div className="brand-card p-8 text-center text-muted-foreground">
          {claimsLoading ? "Loading claims…" : "There are no claims to show a vault for yet."}
        </div>
      ) : (
        <>
          <VaultLanes
            reads={reads}
            money={money}
            handoff={refundMode ? "refund recorded, then a separate transaction pays" : "decision recorded, then a separate transaction pays"}
          />

          <section className="flex flex-wrap items-start gap-6">
            {/* deposits */}
            <div className="flex-[999_1_520px] min-w-0 space-y-4">
              <h2 className="font-[family-name:var(--font-display)] text-2xl font-medium">Deposits on this claim</h2>
              <div className="brand-card divide-y divide-white/5 text-sm">
                <div className="flex items-center justify-between gap-4 p-4">
                  <span className="text-muted-foreground">Held for this claim</span>
                  <span className="font-mono font-medium">{formatGen(held)} GEN</span>
                </div>
                <div className="flex items-center justify-between gap-4 p-4">
                  <span className="text-muted-foreground">Your deposit</span>
                  <span className="font-mono">{address ? `${formatGen(myAmount)} GEN` : "connect a wallet"}</span>
                </div>
                <div className="flex items-center justify-between gap-4 p-4">
                  <span className="text-muted-foreground">Your refund, recorded and waiting to be paid</span>
                  <span className="font-mono">{address ? `${formatGen(myPending)} GEN` : "connect a wallet"}</span>
                </div>
                {release && phase !== "open" && (
                  <div className="flex items-center justify-between gap-4 p-4">
                    <span className="text-muted-foreground">Claimant</span>
                    <span className="font-mono">{short(release.claimant, 10, 6)}</span>
                  </div>
                )}
                {release && phase !== "open" && release.asset && (
                  <div className="flex items-center justify-between gap-4 p-4">
                    <span className="text-muted-foreground">Verified drain bound to this claim</span>
                    <span className="font-mono">{release.boundAmount.toString()} ({short(release.asset, 8, 6)})</span>
                  </div>
                )}
              </div>
              <p className="text-sm text-muted-foreground max-w-[62ch]">
                While a claim is queued or decided, deposits are committed and cannot be pulled back. If the claim is denied, each depositor takes back exactly their own deposit.
              </p>

              {depositOpen && (
                <form
                  className="brand-card p-4 flex flex-wrap items-end gap-3"
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (depositWei) send("deposit_for_claim", [claim.id], depositWei);
                  }}
                >
                  <div className="space-y-2 flex-1 min-w-[180px]">
                    <Label htmlFor="dep-amount">Deposit GEN for this claim</Label>
                    <Input
                      id="dep-amount"
                      inputMode="decimal"
                      placeholder="0.001"
                      value={amountText}
                      onChange={(e) => setAmountText(e.target.value)}
                    />
                  </div>
                  <Button type="submit" variant="outline" disabled={!canAct || !depositWei}>
                    {action.activeFn === "deposit_for_claim" ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                    Deposit
                  </Button>
                </form>
              )}
            </div>

            {/* next step + ledger */}
            <div className="flex-[1_1_340px] min-w-0 space-y-6">
              <div className="brand-card p-5 space-y-4">
                <h2 className="font-[family-name:var(--font-display)] text-xl font-medium">Next step</h2>

                {phase === "settled" && <p className="text-sm text-muted-foreground">This claim's payout has been sent. There is nothing left to do.</p>}

                {phase === "open" && !refundMode && (
                  <>
                    <p className="text-sm text-muted-foreground">
                      Queueing reads the arbiter once, in finalized state. It starts the one-hour challenge window and moves no money. Anyone can press it.
                    </p>
                    <Button variant="gradient" className="w-full min-h-12" disabled={!canAct || status !== "approved" || held <= BigInt(0)} onClick={() => send("queue_release", [claim.id])}>
                      {action.activeFn === "queue_release" && <Loader2 className="h-4 w-4 animate-spin" />}
                      Queue release
                    </Button>
                  </>
                )}

                {queued && (
                  <>
                    <p className="text-sm text-muted-foreground">
                      {windowOver
                        ? "The window has closed. Recording the decision reads the arbiter once more: if the claim changed, the queue is dropped instead of paid."
                        : `Opens in ${clock(windowLeft)}. Anyone can press it. It reads the arbiter once more: if the claim changed, the queue is dropped instead of paid.`}
                    </p>
                    <Button variant="gradient" className="w-full min-h-12" disabled={!canAct || !windowOver} onClick={() => send("release", [claim.id])}>
                      {action.activeFn === "release" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Clock className="h-4 w-4" />}
                      Record release decision
                    </Button>
                    <Button variant="outline" className="w-full" disabled={!canAct} onClick={() => send("cancel_queue", [claim.id])}>
                      Cancel the queue (if the claim was challenged or changed)
                    </Button>
                  </>
                )}

                {phase === "decided" && (
                  <>
                    <p className="text-sm text-muted-foreground">
                      The decision is recorded. This separate step pays {formatGen(release?.pay ?? BigInt(0))} GEN to the claimant, once, and reads nothing.
                    </p>
                    <Button variant="gradient" className="w-full min-h-12" disabled={!canAct} onClick={() => send("settle", [claim.id])}>
                      {action.activeFn === "settle" && <Loader2 className="h-4 w-4 animate-spin" />}
                      Pay the claimant
                    </Button>
                  </>
                )}

                {refundMode && (
                  <>
                    <p className="text-sm text-muted-foreground">
                      A refund is two steps: record it, then pay it. Each depositor can only ever refund their own deposit.
                    </p>
                    <Button variant="gradient" className="w-full min-h-12" disabled={!canAct || myAmount <= BigInt(0)} onClick={() => send("refund", [claim.id])}>
                      {action.activeFn === "refund" && <Loader2 className="h-4 w-4 animate-spin" />}
                      Record my refund
                    </Button>
                  </>
                )}

                {(refundMode || phase === "open") && myPending > BigInt(0) && (
                  <Button variant="outline" className="w-full min-h-12" disabled={!canAct || !address} onClick={() => send("settle_refund", [claim.id, address])}>
                    {action.activeFn === "settle_refund" && <Loader2 className="h-4 w-4 animate-spin" />}
                    Pay my refund ({formatGen(myPending)} GEN)
                  </Button>
                )}

                {!address && <p className="text-xs text-muted-foreground">Connect your wallet to act on this claim.</p>}
                {address && !isOnCorrectNetwork && <p className="text-xs text-yellow-400">Switch to the GenLayer network to act on this claim.</p>}

                {action.isRunning && (
                  <div className="flex items-center justify-between gap-2 border-t border-white/5 pt-3 text-xs text-muted-foreground">
                    {action.pendingTxHash ? (
                      <>
                        <span>Sent. Waiting for the validators…</span>
                        <a href={getTxExplorerUrl(action.pendingTxHash)} target="_blank" rel="noopener noreferrer" className="inline-flex shrink-0 items-center gap-1 font-semibold text-accent hover:underline">
                          View on explorer <ExternalLink className="h-3 w-3" />
                        </a>
                      </>
                    ) : (
                      <span>Checking with the contract, then waiting for your wallet…</span>
                    )}
                  </div>
                )}
              </div>

              <div className="brand-card p-5 space-y-4">
                <div className="flex items-baseline justify-between gap-3">
                  <h2 className="font-[family-name:var(--font-display)] text-xl font-medium">Vault ledger</h2>
                  <span className="text-xs text-muted-foreground">all claims</span>
                </div>
                {accounting ? (
                  <>
                    <div className="flex h-2.5 overflow-hidden rounded-full bg-white/10">
                      <div
                        className="bg-[#e9a93a]"
                        style={{ width: `${accounting.totalReceived > BigInt(0) ? Number((accounting.totalScheduled * BigInt(1000)) / accounting.totalReceived) / 10 : 0}%` }}
                      />
                      <div className="bg-[#4aa3a8]" style={{ width: `${accounting.totalReceived > BigInt(0) ? Number((accounting.unscheduled * BigInt(1000)) / accounting.totalReceived) / 10 : 0}%` }} />
                    </div>
                    <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-2.5 text-sm">
                      <dt className="text-muted-foreground">Received</dt>
                      <dd className="font-mono text-right">{formatGen(accounting.totalReceived)} GEN</dd>
                      <dt className="text-muted-foreground">Scheduled out</dt>
                      <dd className="font-mono text-right">{formatGen(accounting.totalScheduled)} GEN</dd>
                      <dt className="text-muted-foreground">Held now</dt>
                      <dd className="font-mono text-right">{formatGen(accounting.unscheduled)} GEN</dd>
                      <dt className="text-muted-foreground">In flight</dt>
                      <dd className="font-mono text-right">{formatGen(accounting.inFlight)} GEN</dd>
                      <dt className="text-muted-foreground">Shortfall</dt>
                      <dd className={`font-mono text-right ${accounting.shortfall > BigInt(0) ? "text-red-400" : "text-green-400"}`}>{formatGen(accounting.shortfall)} GEN</dd>
                    </dl>
                    <p className="text-xs text-muted-foreground">
                      Every wei in is accounted for. A transfer that never lands shows up as in flight or shortfall, never silently. Payouts land once their transaction finalizes, about 30 minutes.
                    </p>
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">Loading…</p>
                )}
              </div>
            </div>
          </section>
        </>
      )}
    </div>
  );
}

export default function VaultPage() {
  return (
    <div className="min-h-screen flex flex-col">
      <Navbar />
      <main className="flex-grow pt-24 pb-16 px-4 md:px-6 lg:px-8">
        <div className="max-w-7xl mx-auto">
          <Suspense fallback={<div className="brand-card p-8 text-center text-muted-foreground">Loading…</div>}>
            <VaultView />
          </Suspense>
        </div>
      </main>
      <footer className="border-t border-white/10 py-4">
        <div className="max-w-7xl mx-auto px-4 text-center text-sm text-muted-foreground">
          An example consumer of the arbiter, on testnet. Not Salvage's production rescue router.{" "}
          <Link href="/app" className="hover:text-accent">Back to claims</Link>
        </div>
      </footer>
    </div>
  );
}
