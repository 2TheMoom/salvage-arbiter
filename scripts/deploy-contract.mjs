// Deploys one contract to Bradbury with a dedicated testnet wallet kept outside the repo.
//   node scripts/deploy-contract.mjs contracts/recovery_release_vault.py 0x<arbiter>
//   node scripts/deploy-contract.mjs contracts/test_support/mock_arbiter.py
import { readFileSync } from "fs";
import { createAccount, createClient } from "genlayer-js";
import { testnetBradbury } from "genlayer-js/chains";

const [file, ...args] = process.argv.slice(2);
if (!file) {
  console.error("usage: node scripts/deploy-contract.mjs <contract.py> [constructor args...]");
  process.exit(1);
}
const wallets = JSON.parse(readFileSync("C:/Users/olumi/.genlayer-test-wallets/wallets.json", "utf8"));
const client = createClient({ chain: testnetBradbury, account: createAccount(wallets["gl-test-1"].privateKey) });
const code = new Uint8Array(readFileSync(file));
console.log(`deploying ${file} (${code.length} bytes) args=${JSON.stringify(args)}`);
const hash = await client.deployContract({ code, args });
console.log("tx", hash);
const receipt = await client.waitForTransactionReceipt({ hash, status: "ACCEPTED", retries: 200, interval: 5000 });
console.log("exec", receipt.txExecutionResultName);
console.log("ADDRESS", receipt.txDataDecoded?.contractAddress ?? receipt.data?.contract_address);
