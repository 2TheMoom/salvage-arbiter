// Logs the test vault's state and the key balances every minute, so the live UI run can be checked against the chain.
//   VAULT=0x.. node scripts/ui-run-watch.mjs > scripts/ui-run-watch.out
import { readFileSync } from "fs";
import { createClient } from "genlayer-js";
import { testnetBradbury } from "genlayer-js/chains";
const VAULT = process.env.VAULT;
const W = JSON.parse(readFileSync("C:/Users/olumi/.genlayer-test-wallets/wallets.json", "utf8"));
const USER = "0x1a870eA7c2AEC156ff84c83fa4fD30bf9D6be5fb";
const claimant = W["gl-test-2"].address;
const c = createClient({ chain: testnetBradbury });
const plain = (x) => (x instanceof Map ? Object.fromEntries([...x].map(([k, v]) => [k, plain(v)])) : Array.isArray(x) ? x.map(plain) : typeof x === "bigint" ? x.toString() : x);
const bal = async (a) => (await c.getBalance({ address: a })).toString();
const rd = (fn, args = []) => c.readContract({ address: VAULT, functionName: fn, args }).then(plain).catch((e) => "ERR " + String(e.message).slice(0, 60));
for (;;) {
  const row = { t: new Date().toISOString().slice(11, 19), claimantBal: await bal(claimant), userBal: await bal(USER), vaultBal: await bal(VAULT) };
  for (const id of ["ui-run-approved", "ui-run-denied"]) {
    const r = await rd("get_release", [id]);
    row[id] = { phase: r.phase, releaseAt: r.release_at, pay: r.pay, held: await rd("get_deposit", [id]), mine: await rd("get_depositor_amount", [id, USER]), pendingRefund: await rd("get_pending_refund", [id, USER]) };
  }
  row.acct = await rd("get_accounting");
  console.log(JSON.stringify(row));
  await new Promise((r) => setTimeout(r, 60000));
}
