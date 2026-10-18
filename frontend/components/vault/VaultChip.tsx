"use client";

import Link from "next/link";
import { useVaultDeposit, useVaultRelease } from "@/lib/hooks/useVault";
import { formatGen } from "@/lib/utils/gen";

/** A small link on a claim row: what the vault holds for it and where it stands. Renders nothing when there is nothing to show. */
export function VaultChip({ claimId }: { claimId: string }) {
  const { data: held } = useVaultDeposit(claimId);
  const { data: release } = useVaultRelease(claimId);
  if (held === undefined || !release) return null;

  let label: string | null = null;
  if (release.phase === "settled") label = `Paid ${formatGen(release.pay)} GEN`;
  else if (release.phase === "decided") label = `Payout of ${formatGen(release.pay)} GEN decided`;
  else if (release.phase === "queued") label = `Vault holds ${formatGen(held)} GEN, window open`;
  else if (held > BigInt(0)) label = `Vault holds ${formatGen(held)} GEN`;
  if (!label) return null;

  return (
    <Link
      href={`/app/vault?claim=${encodeURIComponent(claimId)}`}
      className="inline-flex shrink-0 items-center rounded-full border border-[#1f5558] bg-[#0f1d1e] px-4 py-2 text-sm font-semibold text-[#6fc0c4] hover:border-[#4aa3a8]"
    >
      {label}
    </Link>
  );
}
