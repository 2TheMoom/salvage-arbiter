// Seeds two test claims on the test-only mock arbiter for the live UI run (third-party wallet gl-test-3 sets them).
//   MOCK=0x.. node scripts/ui-run-seed.mjs
import { readFileSync } from "fs";
import { createAccount, createClient } from "genlayer-js";
import { testnetBradbury } from "genlayer-js/chains";
const MOCK = process.env.MOCK;
const W = JSON.parse(readFileSync("C:/Users/olumi/.genlayer-test-wallets/wallets.json", "utf8"));
const client = createClient({ chain: testnetBradbury, account: createAccount(W["gl-test-3"].privateKey) });
const claimant = W["gl-test-2"].address;
const rows = [
  ["ui-run-approved", claimant, "approved", "native", 5000, 0, "0x00000000000000000000000000000000000a11ce", "Test claim for the live UI run: approved by the stand-in arbiter.", 91],
  ["ui-run-denied", claimant, "denied", "native", 5000, 0, "0x0000000000000000000000000000000000000b0b", "Test claim for the live UI run: denied by the stand-in arbiter.", 84],
];
for (const args of rows) {
  const hash = await client.writeContract({ address: MOCK, functionName: "put_listed", args });
  const r = await client.waitForTransactionReceipt({ hash, status: "ACCEPTED", retries: 100, interval: 5000 });
  console.log(args[0], hash, r.txExecutionResultName, new Date().toISOString());
}
