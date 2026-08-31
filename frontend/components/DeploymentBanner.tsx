"use client";

import { useState } from "react";
import { Github, ExternalLink, Copy, Check } from "lucide-react";
import { getContractAddress } from "@/lib/genlayer/client";
import { formatAddress } from "@/lib/genlayer/wallet";
import { success } from "@/lib/utils/toast";

const EXPLORER_BASE = "https://explorer-bradbury.genlayer.com/address/";
const GITHUB_URL = "https://github.com/2TheMoom/salvage-arbiter";

export function DeploymentBanner() {
  const [copied, setCopied] = useState(false);
  const contractAddress = getContractAddress();

  const handleCopy = async () => {
    if (!contractAddress) return;
    try {
      await navigator.clipboard.writeText(contractAddress);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
      success("Contract address copied!");
    } catch {
      // clipboard access can fail silently in some browser contexts
    }
  };

  return (
    <div className="brand-card px-5 py-3 flex flex-wrap items-center justify-between gap-x-6 gap-y-2 text-sm">
      <div className="flex items-center gap-2">
        <span className="status-dot" />
        <span className="font-semibold">GenLayer Bradbury Testnet</span>
      </div>

      {contractAddress && (
        <div className="flex items-center gap-2 text-muted-foreground">
          <span className="hidden sm:inline">Contract:</span>
          <span className="font-mono text-foreground">{formatAddress(contractAddress, 16)}</span>
          <button
            onClick={handleCopy}
            className="opacity-60 hover:opacity-100 transition-opacity p-0.5 hover:bg-white/5 rounded"
            aria-label="Copy contract address"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-green-400" /> : <Copy className="w-3.5 h-3.5" />}
          </button>
          <a
            href={`${EXPLORER_BASE}${contractAddress}`}
            target="_blank"
            rel="noopener noreferrer"
            className="opacity-60 hover:opacity-100 hover:text-accent transition-colors inline-flex items-center gap-1"
          >
            View on Explorer
            <ExternalLink className="w-3 h-3" />
          </a>
        </div>
      )}

      <a
        href={GITHUB_URL}
        target="_blank"
        rel="noopener noreferrer"
        className="flex items-center gap-1.5 text-muted-foreground hover:text-accent transition-colors"
      >
        <Github className="w-4 h-4" />
        Source
      </a>
    </div>
  );
}
