"use client";

import { Check } from "lucide-react";

export type NodeState = "done" | "active" | "todo";

export interface LaneNode {
  /** Grid column, 1 to 5 */
  col: number;
  fn: string;
  detail: string;
  state: NodeState;
  /** Big text under the function name, for a countdown */
  big?: string;
  /** 0 to 1, a thin bar under the node */
  progress?: number;
}

const TEAL = "#4aa3a8";
const AMBER = "#e9a93a";

function Node({ node, color }: { node: LaneNode; color: string }) {
  const done = node.state === "done";
  const active = node.state === "active";
  return (
    <div
      className="relative flex flex-col items-center text-center gap-1.5"
      style={{ gridColumn: node.col, gridRow: 1 }}
    >
      <span
        className="flex h-6 w-6 items-center justify-center rounded-full box-border"
        style={
          done
            ? { background: color }
            : active
              ? { background: "#0b0906", border: `2px solid ${color}`, boxShadow: `0 0 0 5px ${color}2e` }
              : { background: "#0b0906", border: "2px dashed #4a3d27" }
        }
      >
        {done && <Check className="h-3 w-3 text-black" strokeWidth={3} aria-hidden="true" />}
      </span>
      <span className={`font-mono text-[13px] ${node.state === "todo" ? "text-muted-foreground" : "text-foreground"}`}>
        {node.fn}
      </span>
      {node.big && <span className="font-[family-name:var(--font-display)] text-3xl leading-none">{node.big}</span>}
      {node.progress !== undefined && (
        <span className="block h-1 w-4/5 rounded-full bg-white/10">
          <span className="block h-1 rounded-full" style={{ width: `${Math.round(node.progress * 100)}%`, background: color }} />
        </span>
      )}
      <span className="text-[13px] text-muted-foreground">{node.detail}</span>
    </div>
  );
}

function Lane({ label, note, color, nodes }: { label: string; note: string; color: string; nodes: LaneNode[] }) {
  const doneCols = nodes.filter((n) => n.state === "done").map((n) => n.col);
  const lastDone = doneCols.length ? Math.max(...doneCols) : 0;
  // the lit part of the line runs from the first column to the last finished node
  const litPct = lastDone === 0 ? 0 : ((lastDone - 1) / 4) * 80;
  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex items-center gap-2.5">
        <span className="h-2.5 w-2.5 rounded-sm" style={{ background: color }} />
        <span className="text-xs font-semibold uppercase tracking-[0.12em]" style={{ color }}>
          {label}
        </span>
        <span className="text-[13px] text-muted-foreground">{note}</span>
      </div>
      <div className="relative grid grid-cols-5 gap-x-3">
        <div className="absolute top-[11px] left-[10%] right-[10%] h-0.5 bg-[#3a2e1a]" />
        <div className="absolute top-[11px] left-[10%] h-0.5" style={{ width: `${litPct}%`, background: color }} />
        {nodes.map((n) => (
          <Node key={`${n.col}-${n.fn}`} node={n} color={color} />
        ))}
      </div>
    </div>
  );
}

/** The vault's two lanes: what only reads the arbiter, and what moves money. They never share a transaction. */
export function VaultLanes({ reads, money, handoff }: { reads: LaneNode[]; money: LaneNode[]; handoff: string }) {
  return (
    <section aria-labelledby="lanes-h" className="brand-card p-6 sm:p-8 flex flex-col gap-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="lanes-h" className="font-[family-name:var(--font-display)] text-2xl font-medium">
          Where this claim stands
        </h2>
        <span className="text-sm text-muted-foreground">A decision and a payment never share a transaction.</span>
      </div>
      <div className="overflow-x-auto">
        <div className="min-w-[640px] flex flex-col gap-5">
          <Lane label="Reads the arbiter" note="moves no money" color={TEAL} nodes={reads} />
          <div className="flex items-center gap-3.5 px-1">
            <div className="flex-grow border-t border-dashed border-[#3a2e1a]" />
            <span className="text-xs uppercase tracking-widest text-muted-foreground">{handoff}</span>
            <div className="flex-grow border-t border-dashed border-[#3a2e1a]" />
          </div>
          <Lane label="Moves money" note="reads nothing" color={AMBER} nodes={money} />
        </div>
      </div>
    </section>
  );
}
