# Salvage Arbiter Frontend

Next.js frontend for [Salvage Arbiter](../README.md) — submit fund-recovery claims and
watch GenLayer validators AI-adjudicate them on-chain.

**Routes:** `/` is the marketing landing page; `/app` is the live dashboard (submit,
view, and adjudicate claims). Own visual identity — a "Salvage Torch" gold/coral
palette and a bespoke logomark (`components/Logo.tsx`) — not GenLayer's brand colors
or logo, though the app runs on GenLayer and links back to it.

## Setup

1. Install dependencies:

```bash
npm install
```

2. Create `.env` file:
```bash
cp .env.example .env
```

3. Configure environment variables (see `.env.example`):
   - `NEXT_PUBLIC_CONTRACT_ADDRESS` — RecoveryArbiter contract address (defaults to the
     live Bradbury testnet deployment)
   - `NEXT_PUBLIC_GENLAYER_CHAIN_ID` — 4221 for Bradbury testnet, 61999 for Studio
   - `NEXT_PUBLIC_GENLAYER_RPC_URL` — optional override; leave unset to use the selected
     chain's own built-in RPC

## Development

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

## Build

```bash
npm run build
npm start
```

## Tech Stack

- **Next.js 15** - React framework with App Router
- **TypeScript** - Type safety
- **Tailwind CSS v4** - Styling with a custom glass-morphism theme
- **Fraunces + Plus Jakarta Sans** (`next/font/google`) - display serif + body sans
- **genlayer-js** - GenLayer blockchain SDK
- **TanStack Query (React Query)** - Data fetching and caching
- **Radix UI** - Accessible component primitives
- **shadcn/ui** - Pre-built UI components

## Wallet

Wallet connection is via **MetaMask** (see `lib/genlayer/WalletProvider.tsx`), not a
local private-key manager. Connecting prompts MetaMask to add/switch to the configured
GenLayer network (Bradbury testnet by default) automatically.

## Features

- **Submit Claims**: Assert ownership of a drained wallet, link public evidence, and
  explain your case
- **View Claims**: Real-time table of every claim with status, claimant, and verdict
- **Adjudicate**: Anyone connected can trigger AI adjudication on a pending claim —
  validators fetch the evidence, reason over it with an LLM, and reach consensus via
  GenLayer's equivalence principle
- **Appeal**: The original claimant can appeal a denied/insufficient claim with new
  evidence (up to 3 times), which resets it to pending and re-triggers adjudication in
  one action
- **Profile** (`/app/profile`): wallet details and your full claim history, reachable
  from the account icon next to the connected-wallet pill
- **Glass-morphism UI**: Dark theme with OKLCH colors, backdrop blur, and animations
