"use client";

import Link from "next/link";
import { useQueries } from "@tanstack/react-query";
import { useClaims } from "@/lib/hooks/useRecoveryArbiter";
import { useVaultContract } from "@/lib/hooks/useVault";
import { useWallet } from "@/lib/genlayer/wallet";
import { formatGen } from "@/lib/utils/gen";

/** The connected wallet's deposits across every claim. The vault has no depositor index, so this asks about each claim in turn. */
export function MyVaultDeposits() {
  const vault = useVaultContract();
  const { address } = useWallet();
  const { data: claims } = useClaims();

  const rows = useQueries({
    queries: (claims ?? []).map((c) => ({
      queryKey: ["vaultPosition", c.id, address],
      queryFn: async () => {
        const [amount, pendingRefund] = await Promise.all([
          vault!.getDepositorAmount(c.id, address!),
          vault!.getPendingRefund(c.id, address!),
        ]);
        return { id: c.id, wallet: c.drained_wallet, amount, pendingRefund };
      },
      enabled: !!vault && !!address,
      staleTime: 5000,
    })),
  });

  if (!vault || !address) return null;

  const mine = rows.map((r) => r.data).filter((d): d is NonNullable<typeof d> => !!d && (d.amount > BigInt(0) || d.pendingRefund > BigInt(0)));
  const held = mine.reduce((sum, d) => sum + d.amount, BigInt(0));
  const waiting = mine.reduce((sum, d) => sum + d.pendingRefund, BigInt(0));
  const loading = rows.some((r) => r.isLoading);

  return (
    <section aria-labelledby="my-deposits-h" className="brand-card p-6 space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="my-deposits-h" className="text-xl font-bold">My vault deposits</h2>
        <span className="text-xs font-semibold uppercase tracking-widest text-[#6fc0c4]">New</span>
      </div>
      <div className="flex flex-wrap gap-8">
        <div className="space-y-1">
          <p className="text-sm text-muted-foreground">Held for claims</p>
          <p className="font-mono text-xl">{formatGen(held)} GEN</p>
        </div>
        <div className="space-y-1">
          <p className="text-sm text-muted-foreground">Refund recorded, waiting to be paid</p>
          <p className="font-mono text-xl">{formatGen(waiting)} GEN</p>
        </div>
      </div>
      {loading && <p className="text-sm text-muted-foreground">Checking your claims…</p>}
      {!loading && mine.length === 0 && <p className="text-sm text-muted-foreground">You have no deposits in the vault.</p>}
      {mine.length > 0 && (
        <ul className="divide-y divide-white/5 text-sm">
          {mine.map((d) => (
            <li key={d.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
              <span className="font-mono">{d.wallet.length > 24 ? `${d.wallet.slice(0, 14)}…${d.wallet.slice(-6)}` : d.wallet}</span>
              <span className="font-mono text-muted-foreground">
                {formatGen(d.amount)} GEN{d.pendingRefund > BigInt(0) ? `, refund ${formatGen(d.pendingRefund)} waiting` : ""}
              </span>
              <Link href={`/app/vault?claim=${encodeURIComponent(d.id)}`} className="font-semibold text-accent hover:underline">
                Open
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
