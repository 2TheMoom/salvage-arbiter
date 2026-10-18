// Waits until the test claim is visible to the vault in FINALIZED state (queue_release stops being refused), then prints READY.
import { readFileSync } from "fs";
import { createAccount, createClient } from "genlayer-js";
import { testnetBradbury } from "genlayer-js/chains";
const V = process.env.VAULT;
const W = JSON.parse(readFileSync("C:/Users/olumi/.genlayer-test-wallets/wallets.json", "utf8"));
const c = createClient({ chain: testnetBradbury, account: createAccount(W["gl-test-3"].privateKey) });
for (;;) {
  try {
    await c.simulateWriteContract({ address: V, functionName: "queue_release", args: ["ui-run-approved"] });
    console.log("READY", new Date().toISOString());
    break;
  } catch (e) {
    console.log(new Date().toISOString().slice(11, 19), "not yet:", String(e.message).slice(0, 60));
  }
  await new Promise((r) => setTimeout(r, 60000));
}
