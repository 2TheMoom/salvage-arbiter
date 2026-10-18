// Live end-to-end run of RecoveryReleaseVault v2 on Bradbury, with separate depositor, claimant and third-party wallets.
//   VAULT_M=0x.. MOCK=0x.. VAULT_R=0x.. node scripts/vault-e2e.mjs      (writes scripts/vault-e2e-log.json)
//   ONLY=release,challenge,real node ...                               runs just those
//
// Scenarios (each its own claim, run concurrently, every write confirmed by reading state back):
//   release    vault-M (stand-in arbiter): a claim approved in the arbiter's FINALIZED state is queued, release is refused inside the
//              challenge window, then recorded, then paid in its own transaction: the claimant gains exactly the deposit
//   challenge  vault-M: a queued claim is challenged during the window; release is refused, the queue is cancelled; the claim is
//              then denied and both depositors take back exactly their own deposit
//   real       vault-R (the REAL deployed RecoveryArbiter): a real claim is filed with a real ownership signature; the vault reads
//              the real arbiter's finalized record (pending, then denied) and refunds the depositor exactly
// The stand-in arbiter is test-only (anyone can set any status); the real one is the deployed contract. Every refusal is simulated
// first so the contract's own reason is recorded, then sent so the refusal is on chain.
import { readFileSync, writeFileSync } from "fs";
import { createAccount, createClient } from "genlayer-js";
import { testnetBradbury } from "genlayer-js/chains";

const VAULT_M = process.env.VAULT_M, MOCK = process.env.MOCK, VAULT_R = process.env.VAULT_R;
const REAL_ARBITER = process.env.ARBITER || "0x3e5515cFd2CdFed30712b1b958e57D09143943b3";
if (!VAULT_M || !MOCK || !VAULT_R) {
  console.error("set VAULT_M, MOCK and VAULT_R");
  process.exit(1);
}
const LOGFILE = process.env.E2E_LOG || "scripts/vault-e2e-log.json";
const ONLY = process.env.ONLY ? process.env.ONLY.split(",") : null;
const RUN = Date.now().toString(36);
const WINDOW = 3600;
const GEN = 10n ** 18n;
const AMOUNT = GEN / 500n; // 0.002
const HALF = GEN / 1000n; // 0.001

const WALLETS = JSON.parse(readFileSync("C:/Users/olumi/.genlayer-test-wallets/wallets.json", "utf8"));
const names = ["gl-test-1", "gl-test-2", "gl-test-3", "gl-test-4"]; // depositor A, claimant, third party, depositor B
const acct = Object.fromEntries(names.map((n) => [n, createAccount(WALLETS[n].privateKey)]));
const addr = Object.fromEntries(names.map((n) => [n, WALLETS[n].address]));
const clients = Object.fromEntries(names.map((n) => [n, createClient({ chain: testnetBradbury, account: acct[n] })]));
const reader = createClient({ chain: testnetBradbury });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const now = () => Math.floor(Date.now() / 1000);
const plain = (x) => (x instanceof Map ? Object.fromEntries([...x].map(([k, v]) => [k, plain(v)])) : Array.isArray(x) ? x.map(plain) : typeof x === "bigint" ? x.toString() : x);
const gen = (w) => (Number(w) / 1e18).toFixed(6);

const LOG = { vaultM: VAULT_M, mock: MOCK, vaultR: VAULT_R, realArbiter: REAL_ARBITER, run: RUN, started: new Date().toISOString(), events: [], results: {} };
function log(scn, msg, extra) {
  console.log(`[${new Date().toISOString().slice(11, 19)}] ${scn.padEnd(9)} ${msg}`);
  LOG.events.push({ t: new Date().toISOString(), scenario: scn, msg, ...(extra || {}) });
  writeFileSync(LOGFILE, JSON.stringify(LOG, null, 1));
}

const queues = {};
function serial(who, fn) {
  const run = (queues[who] || Promise.resolve()).then(fn, fn);
  queues[who] = run.catch(() => {});
  return run;
}

async function rd(address, fn, args = []) {
  for (let i = 0; ; i++) {
    try {
      return plain(await reader.readContract({ address, functionName: fn, args }));
    } catch (e) {
      if (i >= 6) throw e;
      await sleep(8000);
    }
  }
}

/** The contract's own refusal text, decoded from the node's error (the reason arrives as raw bytes inside the message). */
function reasonOf(err) {
  const text = String(err?.message || err);
  const m = text.match(/ReturnData:\[\]uint8\{([^}]*)\}/);
  if (m) {
    const bytes = m[1].split(",").map((s) => parseInt(s.trim(), 16)).filter((n) => !Number.isNaN(n));
    const runs = [];
    let cur = "";
    for (const b of bytes) {
      if (b >= 32 && b < 127) cur += String.fromCharCode(b);
      else { if (cur.length >= 10) runs.push(cur); cur = ""; }
    }
    if (cur.length >= 10) runs.push(cur);
    const sentence = runs.find((r) => r.includes(" "));
    if (sentence) return sentence;
  }
  return text.replace(/\s+/g, " ").slice(0, 160);
}

async function waitAccepted(who, hash) {
  for (let a = 1; ; a++) {
    try {
      return await clients[who].waitForTransactionReceipt({ hash, status: "ACCEPTED", retries: 200, interval: 5000 });
    } catch (e) {
      if (a >= 8) throw e;
      await sleep(15000);
    }
  }
}

function send(scn, who, address, fn, args, value) {
  return serial(who, async () => {
    let hash;
    for (let a = 1; ; a++) {
      try {
        hash = await clients[who].writeContract({ address, functionName: fn, args, ...(value ? { value } : {}) });
        break;
      } catch (e) {
        if (a >= 6) throw e;
        await sleep(10000);
      }
    }
    const r = await waitAccepted(who, hash);
    const exec = r.txExecutionResultName;
    log(scn, `${address === MOCK ? "mock" : address === REAL_ARBITER ? "arbiter" : "vault"}.${fn} ${hash.slice(0, 12)} exec=${exec}`, { fn, hash, exec });
    return { hash, exec };
  });
}

/** A write the contract must refuse: simulate it for the reason, then send it so the refusal is on chain too. */
async function refused(scn, who, address, fn, args, expect) {
  let reason = "";
  try {
    await clients[who].simulateWriteContract({ address, functionName: fn, args });
    reason = "SIMULATION ACCEPTED";
  } catch (e) {
    reason = reasonOf(e);
  }
  if (reason === "SIMULATION ACCEPTED") throw new Error(`${scn}: ${fn} should have been refused`);
  if (expect && !reason.includes(expect)) throw new Error(`${scn}: ${fn} was refused for "${reason}", expected "${expect}"`);
  return serial(who, async () => {
    let hash = null, exec = "refused before it was sent";
    try {
      hash = await clients[who].writeContract({ address, functionName: fn, args });
      const r = await waitAccepted(who, hash);
      exec = r.txExecutionResultName;
      if (exec === "FINISHED_WITH_RETURN") throw new Error(`${scn}: ${fn} was accepted but should have been refused`);
    } catch (e) {
      if (String(e.message).includes("was accepted but")) throw e;
    }
    log(scn, `${fn} refused: "${reason}" (${hash ? hash.slice(0, 12) + " " : ""}${exec})`, { fn, hash, exec, reason, refused: true });
    return { refused: true, hash, reason };
  });
}

async function finalized(scn, hash, label) {
  const t0 = Date.now();
  for (let a = 0; a < 20; a++) {
    try {
      await reader.waitForTransactionReceipt({ hash, status: "FINALIZED", retries: 400, interval: 10000 });
      const m = ((Date.now() - t0) / 60000).toFixed(1);
      log(scn, `${label} FINALIZED ${m} min after the wait began`, { label, finalizedAfterMinutes: Number(m) });
      return Number(m);
    } catch {
      await sleep(15000);
    }
  }
  throw new Error(`${scn}: ${label} did not finalize in time`);
}

const balance = async (a) => BigInt(await reader.getBalance({ address: a }));
const rel = (vault, cid) => rd(vault, "get_release", [cid]);
const mockPut = (scn, cid, status, challenges = 0) => send(scn, "gl-test-3", MOCK, "put", [cid, addr["gl-test-2"], status, "native", 5000, challenges]);

async function until(scn, what, getter, pred, tries = 40) {
  for (let i = 0; i < tries; i++) {
    const x = await getter().catch(() => null);
    if (x && pred(x)) return x;
    await sleep(10000);
  }
  throw new Error(`${scn}: timed out waiting for ${what}`);
}

// -------------------------------------------------------------------------------------------------------------------------

async function release() {
  const scn = "release";
  const cid = `rel-${RUN}`;
  await send(scn, "gl-test-1", VAULT_M, "deposit_for_claim", [cid], AMOUNT);
  const put = await mockPut(scn, cid, "approved");
  // the arbiter's approval is accepted but not final: the vault must not act on it yet
  await refused(scn, "gl-test-3", VAULT_M, "queue_release", [cid], "could not be read");
  await finalized(scn, put.hash, "the arbiter's approval");
  const q = await send(scn, "gl-test-3", VAULT_M, "queue_release", [cid]);
  const queued = await until(scn, "queued", () => rel(VAULT_M, cid), (r) => r.phase === "queued");
  log(scn, `queued at ${new Date(Number(queued.queued_at) * 1000).toISOString()}, release allowed from ${new Date(Number(queued.release_at) * 1000).toISOString()}`, { queuedAt: queued.queued_at, releaseAt: queued.release_at });
  await refused(scn, "gl-test-3", VAULT_M, "release", [cid], "window is still open");
  const wait = Number(queued.release_at) + 30 - now();
  log(scn, `waiting ${Math.ceil(wait / 60)} min for the challenge window to close`);
  await sleep(Math.max(0, wait) * 1000);
  const r1 = await send(scn, "gl-test-3", VAULT_M, "release", [cid]);
  const decided = await until(scn, "decided", () => rel(VAULT_M, cid), (r) => r.phase === "decided");
  log(scn, `decision recorded: pay ${gen(decided.pay)} GEN to the claimant, no money moved yet`, { pay: decided.pay });
  await finalized(scn, r1.hash, "the release decision");
  const before = await balance(addr["gl-test-2"]);
  const s = await send(scn, "gl-test-3", VAULT_M, "settle", [cid]);
  const done = await until(scn, "settled", () => rel(VAULT_M, cid), (r) => r.phase === "settled");
  await finalized(scn, s.hash, "settle");
  const after = await balance(addr["gl-test-2"]);
  await refused(scn, "gl-test-3", VAULT_M, "settle", [cid], "No payout decision");
  log(scn, `claimant balance ${gen(before)} -> ${gen(after)}: +${gen(after - before)} (deposit ${gen(AMOUNT)}), claimant sent nothing`, { claimantDelta: (after - before).toString() });
  if (after - before !== AMOUNT) throw new Error(`${scn}: the claimant gained ${after - before}, expected ${AMOUNT}`);
  LOG.results.release = { phase: done.phase, claimantDelta: (after - before).toString(), queueTx: q.hash, releaseTx: r1.hash, settleTx: s.hash };
}

async function challenge() {
  const scn = "challenge";
  const cid = `chal-${RUN}`;
  await send(scn, "gl-test-1", VAULT_M, "deposit_for_claim", [cid], HALF);
  await send(scn, "gl-test-4", VAULT_M, "deposit_for_claim", [cid], HALF);
  const put1 = await mockPut(scn, cid, "approved");
  await finalized(scn, put1.hash, "the arbiter's approval");
  await send(scn, "gl-test-3", VAULT_M, "queue_release", [cid]);
  const queued = await until(scn, "queued", () => rel(VAULT_M, cid), (r) => r.phase === "queued");
  // someone challenges the approved claim inside the window
  const put2 = await mockPut(scn, cid, "challenged", 1);
  await finalized(scn, put2.hash, "the challenge");
  const wait = Number(queued.release_at) + 30 - now();
  log(scn, `waiting ${Math.ceil(Math.max(0, wait) / 60)} min for the challenge window to close`);
  await sleep(Math.max(0, wait) * 1000);
  await refused(scn, "gl-test-3", VAULT_M, "release", [cid], "changed since it was queued");
  await refused(scn, "gl-test-1", VAULT_M, "refund", [cid], "queued or decided"); // committed money cannot be pulled while queued
  await send(scn, "gl-test-3", VAULT_M, "cancel_queue", [cid]);
  await until(scn, "open", () => rel(VAULT_M, cid), (r) => r.phase === "open");
  await refused(scn, "gl-test-1", VAULT_M, "refund", [cid], "Refunds open when"); // challenged is not denied
  const put3 = await mockPut(scn, cid, "denied", 1);
  await finalized(scn, put3.hash, "the denial");
  const rA = await send(scn, "gl-test-1", VAULT_M, "refund", [cid]);
  const rB = await send(scn, "gl-test-4", VAULT_M, "refund", [cid]);
  await finalized(scn, rA.hash, "refund request A");
  await finalized(scn, rB.hash, "refund request B");
  const a0 = await balance(addr["gl-test-1"]);
  const b0 = await balance(addr["gl-test-4"]);
  const sA = await send(scn, "gl-test-3", VAULT_M, "settle_refund", [cid, addr["gl-test-1"]]);
  const sB = await send(scn, "gl-test-3", VAULT_M, "settle_refund", [cid, addr["gl-test-4"]]);
  await finalized(scn, sA.hash, "settle_refund A");
  await finalized(scn, sB.hash, "settle_refund B");
  const a1 = await balance(addr["gl-test-1"]);
  const b1 = await balance(addr["gl-test-4"]);
  await refused(scn, "gl-test-3", VAULT_M, "settle_refund", [cid, addr["gl-test-1"]], "No refund to settle");
  log(scn, `depositor A ${gen(a0)} -> ${gen(a1)} (+${gen(a1 - a0)}), depositor B ${gen(b0)} -> ${gen(b1)} (+${gen(b1 - b0)}), each deposited ${gen(HALF)}`, { aDelta: (a1 - a0).toString(), bDelta: (b1 - b0).toString() });
  if (a1 - a0 !== HALF || b1 - b0 !== HALF) throw new Error(`${scn}: refunds were ${a1 - a0} and ${b1 - b0}, expected ${HALF} each`);
  LOG.results.challenge = { aDelta: (a1 - a0).toString(), bDelta: (b1 - b0).toString() };
}

async function real() {
  const scn = "real";
  // a throwaway key only signs the ownership message; the drained wallet is not a real victim and no real drain is cited
  const drained = createAccount();
  const claimant = acct["gl-test-2"].address;
  const message = `I authorize ${claimant} to submit a Salvage Arbiter recovery claim on behalf of ${drained.address}.`;
  const signature = await drained.signMessage({ message });
  const sub = await send(scn, "gl-test-2", REAL_ARBITER, "submit_claim", [drained.address, "https://example.com/", "Vault live verification: no real drain, a bogus transaction is cited.", signature, "0x" + "00".repeat(32)]);
  const ids = await until(scn, "the claim to be listed", () => rd(REAL_ARBITER, "get_claims_by_address", [claimant]), (l) => Array.isArray(l) && l.length > 0);
  const cid = ids[ids.length - 1].id;
  log(scn, `real claim filed on the real arbiter: ${cid.slice(0, 18)}...`, { claimId: cid });
  await send(scn, "gl-test-1", VAULT_R, "deposit_for_claim", [cid], AMOUNT);
  await refused(scn, "gl-test-3", VAULT_R, "queue_release", [cid], "could not be read"); // the claim is not in the arbiter's FINALIZED state yet
  await finalized(scn, sub.hash, "the real claim's submission");
  await refused(scn, "gl-test-3", VAULT_R, "queue_release", [cid], "status: pending"); // the vault has now read the real arbiter's finalized claim
  await refused(scn, "gl-test-1", VAULT_R, "refund", [cid], "Refunds open when");
  const adj = await send(scn, "gl-test-3", REAL_ARBITER, "adjudicate", [cid]);
  const verdict = await until(scn, "a verdict", () => rd(REAL_ARBITER, "get_claim_status", [cid]), (s) => typeof s === "string" && s !== "pending", 80);
  log(scn, `the real arbiter's verdict: ${verdict}`, { verdict });
  await finalized(scn, adj.hash, "the real arbiter's verdict");
  if (verdict === "approved") throw new Error(`${scn}: a bogus drain was approved, stopping`);
  const rq = await send(scn, "gl-test-1", VAULT_R, "refund", [cid]);
  await finalized(scn, rq.hash, "the refund request");
  const a0 = await balance(addr["gl-test-1"]);
  const st = await send(scn, "gl-test-3", VAULT_R, "settle_refund", [cid, addr["gl-test-1"]]);
  await finalized(scn, st.hash, "settle_refund");
  const a1 = await balance(addr["gl-test-1"]);
  log(scn, `depositor ${gen(a0)} -> ${gen(a1)} (+${gen(a1 - a0)}), deposited ${gen(AMOUNT)}`, { delta: (a1 - a0).toString() });
  if (a1 - a0 !== AMOUNT) throw new Error(`${scn}: the refund was ${a1 - a0}, expected ${AMOUNT}`);
  LOG.results.real = { verdict, claimId: cid, delta: (a1 - a0).toString() };
}

const all = { release, challenge, real };
const order = Object.keys(all).filter((k) => !ONLY || ONLY.includes(k));
const settled = await Promise.allSettled(order.map((k) => all[k]()));
settled.forEach((s, i) => {
  if (s.status === "rejected") log(order[i], `FAILED: ${String(s.reason?.message || s.reason).slice(0, 900)}`);
});
LOG.accountingMock = await rd(VAULT_M, "get_accounting");
LOG.accountingReal = await rd(VAULT_R, "get_accounting");
LOG.finished = new Date().toISOString();
writeFileSync(LOGFILE, JSON.stringify(LOG, null, 1));
console.log("\nRESULTS", JSON.stringify(LOG.results, null, 1), "\nACCOUNTING mock", JSON.stringify(LOG.accountingMock), "\nACCOUNTING real", JSON.stringify(LOG.accountingReal));
