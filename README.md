# Salvage Arbiter

## About
An Intelligent Contract on [GenLayer](https://genlayer.foundation) that adjudicates
cryptocurrency fund-recovery claims. A claimant asserts ownership of a compromised/
drained wallet and points to public evidence (a signed message, a social post proving
control of the address, etc). GenLayer validators independently fetch that evidence,
reason over it with an LLM, and reach consensus on a verdict — approved, denied, or
insufficient — via the equivalence principle. The result is an on-chain attestation
that an off-chain recovery flow (e.g. Salvage's cross-chain rescue router) can require
before releasing recovered funds to a claimant, instead of relying solely on
manual/offline verification.

A denied or insufficient verdict isn't final: the claimant can appeal with new evidence
(`submit_appeal`), which resets the claim to `pending` and clears the old verdict so
`adjudicate` reconsiders it from scratch. Appeals are capped at 3 per claim and
restricted to the original claimant, so the AI's non-determinism can't be gamed by
spam-retrying an unchanged submission.

Ownership itself is settled by cryptography, not AI judgment: `submit_claim` requires
an EIP-191 signature proving control of the drained wallet's private key, verified via
a pure-Python secp256k1 ECDSA recovery running identically on every validator (no
external RPC dependency for this check — see "Design notes" below for why). The LLM's
job is judging whether the claimant's stated circumstances are coherent and consistent
with an independently-fetched, authoritative on-chain balance fact, not re-litigating
identity. A wallet can only ever have one approved claim: `submit_claim` rejects new
submissions once one exists, and `adjudicate` re-checks the same condition again right
before approving, so two claims filed for the same wallet while both are still pending
can't both end up approved — whichever is adjudicated second is auto-denied, citing the
first claim's ID, without even consulting the LLM. That check is canonicalization-safe:
`eth:0xABC...`, `0xabc...`, and `ETH:0xAbC...` all resolve to the same internal wallet
key, so the guarantee can't be dodged by reformatting the address string.

## Live deployment
Deployed and verified on **GenLayer Bradbury Testnet** (chain ID 4221):
- **Contract:** [`0x3C16fA8C61229B6FCDf87b31d475654e9DFea427`](https://explorer-bradbury.genlayer.com/address/0x3C16fA8C61229B6FCDf87b31d475654e9DFea427)
- Verified via 71 passing direct-mode tests (`pytest tests/direct/`), including four
  adversarial tests that reproduce a wallet-address canonicalization bypass: the same
  real wallet submitted under different chain-prefix/case formatting must still be
  recognized as one wallet by the duplicate-claim check, the competing-claim guard
  (both at submission and at adjudication time), and `get_claims_for_wallet`.
- Previous deployments (superseded, kept for history):
  [competing-claim-at-adjudication fix, pre-canonicalization](https://explorer-bradbury.genlayer.com/address/0xc4e01803B993191f75e294B71F61a042e135F70F)
  (approved_wallets/wallet_claims were keyed by the raw, unnormalized address string,
  so the same wallet resubmitted with different formatting could dodge the
  one-approved-claim-per-wallet guarantee — the gap this deployment closes),
  [signature + chain-check + first competing-claim pass](https://explorer-bradbury.genlayer.com/address/0x1310D205603851E9c78182b67F52Fe6a2B60041C),
  [appeal-path only](https://explorer-bradbury.genlayer.com/address/0xdc1801D971483eCf4Afd582c19a176419F61Bbcc),
  [original, pre-appeal](https://explorer-bradbury.genlayer.com/address/0x228a8083aBc7961bef6cAeC2C0f19F288A3c5D03).

### Design notes
- **Signature verification uses no external RPC.** An earlier version called a public
  RPC's `ecrecover` precompile from within the equivalence-principle nondet mechanism.
  Live testing showed this was unreliable: different validators' calls to the same
  provider could return inconsistent results for the identical, deterministic
  computation (observed both as an opaque gateway-side "Internal error" and as
  outright request blocking without a browser-like `User-Agent`), causing spurious
  consensus failures. A pure-Python secp256k1 implementation has no such failure
  mode — every validator runs identical bytecode on identical input and always agrees
  — so it replaced the RPC call entirely for this specific, security-critical check.
- **The `genlayer` CLI's `--args` parser is not schema-aware.** While debugging the
  above, a raw hex-string signature passed via `genlayer write ... --args` arrived
  inside the contract as a Python `int`, not a `str` — the CLI guesses argument types
  from the literal command-line string's shape, unlike `genlayer-js`'s `writeContract`,
  which encodes arguments according to the contract's own declared schema. This only
  affects CLI-based testing; the frontend (using `genlayer-js` directly, like any real
  user's browser would) was unaffected and is what the verification above used.
- **The frontend now surfaces a transaction hash as soon as one exists, not only on
  final success.** The original submit/adjudicate/appeal flows only returned a tx hash
  after `waitForTransactionReceipt` fully resolved, so a slow or stuck confirmation
  (this testnet's validator rounds can occasionally stall, per the section above) looked
  identical to nothing having happened at all - no hash, no error, just a spinner. Each
  write now reports its hash immediately after broadcast via a callback, the UI shows a
  "view on explorer" link while waiting, and a confirmation timeout's error message
  includes the hash so the transaction can still be checked instead of looking silently
  dropped. Fee estimation (a pre-flight network call) is also now bounded to a 10s
  timeout and falls back to default fees rather than being able to block the whole
  submission indefinitely if it hangs.

This started from GenLayer's official
[project boilerplate](https://github.com/genlayerlabs/genlayer-project-boilerplate);
the original `football_bets.py` sample contract and its tests are kept around under
`contracts/` and `tests/` as a working reference for the SDK patterns (web fetch + LLM
+ equivalence principle) this project builds on.

## What's included
- `contracts/recovery_arbiter.py` — the RecoveryArbiter Intelligent Contract
- `tests/direct/test_recovery_arbiter.py` — direct-mode tests (in-memory, mocked web/LLM)
- **Contract linting** — static analysis to catch common contract issues before deployment
- **CI pipeline** — GitHub Actions workflow for linting and direct tests
- A Next.js 15 frontend (TypeScript, TanStack Query, Radix UI) wired to
  RecoveryArbiter — submit claims, view/adjudicate them, and track your own claim
  history (see `frontend/README.md`)
- Configuration file template and deployment scripts

## Requirements
- Python >= 3.12
- [GenLayer CLI](https://github.com/genlayerlabs/genlayer-cli) globally installed: `npm install -g genlayer`
- GenLayer Studio (for integration tests and deployment): Install from [Docs](https://docs.genlayer.com/developers/intelligent-contracts/tooling-setup#using-the-genlayer-studio) or use the hosted [GenLayer Studio](https://studio.genlayer.com/)

## Project Structure

```
contracts/              # Python intelligent contracts
tests/
  direct/               # Fast in-memory tests (no Studio required)
    test_create_bet.py   # Bet creation logic
    test_resolve_bet.py  # Bet resolution with web/LLM mocks
    test_views.py        # Read-only view methods
  integration/           # Full tests against GenLayer Studio
    test_football_bets.py
    fixtures.py          # Expected state fixtures
frontend/               # Next.js 15 app (TypeScript, TanStack Query, Radix UI)
deploy/                 # TypeScript deployment scripts
gltest.config.yaml      # Test runner network configuration
pyproject.toml          # Python/pytest configuration
.github/workflows/      # CI pipeline
```

## Quick Start

### 1. Set up Python environment

```shell
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Lint your contracts

Run the GenVM linter to catch issues before deployment:

```shell
genvm-lint check contracts/football_bets.py
```

The linter catches:
- Forbidden imports and non-deterministic calls
- Invalid storage types (must use `TreeMap`, `DynArray`, `u256`, etc.)
- Missing decorators and return type annotations
- Non-deterministic operations outside equivalence principle blocks
- And [20+ other rules](https://github.com/genlayerlabs/genvm-linter)

### 3. Run direct mode tests

Direct mode tests run contracts in-memory without needing GenLayer Studio. They use mocks for web requests and LLM calls, giving you fast feedback (~milliseconds per test):

```shell
pytest tests/direct/ -v
```

Direct mode features used in these tests:
- `direct_deploy("contracts/file.py")` — deploy contract in memory
- `direct_vm.sender = address` — set transaction sender
- `direct_vm.mock_web(pattern, response)` — mock HTTP/render calls
- `direct_vm.mock_llm(pattern, response)` — mock LLM responses
- `direct_vm.expect_revert("message")` — assert expected failures
- `direct_vm.clear_mocks()` — reset mocks between calls

### 4. Deploy the contract

1. Choose your network: `genlayer network`
2. Deploy: `genlayer deploy` (runs the script in `/deploy/deployScript.ts`)

### 5. Run integration tests

Integration tests deploy the contract to GenLayer Studio and test with real consensus:

```shell
gltest tests/integration/ -v -s
```

These require GenLayer Studio running (local or hosted).

### 6. Set up the frontend

1. Copy `frontend/.env.example` to `frontend/.env`
2. Add your deployed contract address as `NEXT_PUBLIC_CONTRACT_ADDRESS`
3. Run:

```shell
cd frontend
npm install
npm run dev
```

The app will be available at http://localhost:3000/.

## How RecoveryArbiter Works

1. **`submit_claim(drained_wallet, evidence_url, statement, signature)`** — a claimant
   registers a claim over an (external-chain) drained wallet address, with an EIP-191
   signature proving control of it, plus public evidence and their case. Returns a
   `claim_id`; fails if the signature doesn't recover to `drained_wallet`, or if that
   wallet already has an approved claim.
2. **`adjudicate(claim_id)`** — first re-checks whether `drained_wallet` already has a
   *different* approved claim (possible if two claims were filed for the same wallet
   while both were still pending) and auto-denies this one if so, without calling the
   LLM. Otherwise fetches `evidence_url` live plus an authoritative on-chain balance for
   `drained_wallet`, asks an LLM whether the evidence and statement are coherent given
   that fact, and reaches multi-validator consensus on the verdict via the
   leader/validator equivalence-principle pattern (validators agree on the `verdict`
   field even if reasoning text differs). Sets `status` to `approved`, `denied`, or
   `insufficient`, plus a `confidence` (0–100) and `reasoning`.
3. **`submit_appeal(claim_id, evidence_url, statement)`** — the original claimant only,
   and only on a `denied`/`insufficient` claim, can replace the evidence/statement and
   reset `status` back to `pending` (clearing the old verdict) so `adjudicate` can
   reconsider. Capped at `MAX_APPEALS = 3` per claim to stop someone from spam-retrying
   an unchanged submission hoping the LLM's non-determinism eventually flips the result.
4. **`get_claim` / `get_claims_by_address` / `get_all_claims`** — read back claims and
   verdicts for an off-chain system to act on.

### A CLI gotcha worth knowing
`genlayer write/call --args` auto-coerces any bare `0x` + 40-hex-char argument into a
GenVM `Address` calldata type — even for a parameter declared `str` in the contract
(like `drained_wallet`, which references an *external*-chain address, not a native
GenLayer one). Passing a raw address string that way fails at runtime with
`AttributeError: 'int' object has no attribute 'encode'`. Work around it in manual CLI
testing by prefixing the value (e.g. `"eth:0x000...deadbeef"`) so it doesn't match the
address pattern; a real frontend using `genlayer-js` with explicit typed args doesn't
have this ambiguity.

## Testing Strategy

| Test Type | Command | Speed | Requires Studio |
|-----------|---------|-------|-----------------|
| **Lint** | `genvm-lint check contracts/*.py` | ~250ms | No |
| **Direct** | `pytest tests/direct/ -v` | ~ms/test | No |
| **Integration** | `gltest tests/integration/ -v -s` | ~min/test | Yes |

**Recommended workflow:**
1. Lint after every contract change
2. Run direct tests frequently during development
3. Run integration tests before deployment to verify consensus behavior

For AI coding agents (Claude Code, Cursor, etc.), the linter and direct tests provide the fast feedback loop needed for iterative development without requiring a running Studio instance.

## Community
- **[Discord](https://discord.gg/8Jm4v89VAu)**: Discussions, support, and announcements
- **[Telegram](https://t.me/genlayer)**: Informal chats and quick updates

## Documentation
For detailed information, see our [documentation](https://docs.genlayer.com/).

## License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
