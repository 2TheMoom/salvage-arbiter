import { readFileSync } from "fs";
import path from "path";
import {
  TransactionHash,
  TransactionStatus,
  GenLayerClient,
  DecodedDeployData,
  GenLayerChain,
} from "genlayer-js/types";
import { localnet } from "genlayer-js/chains";

async function deployOne(
  client: GenLayerClient<any>,
  relativePath: string,
  args: any[]
): Promise<string> {
  const filePath = path.resolve(process.cwd(), relativePath);
  const contractCode = new Uint8Array(readFileSync(filePath));

  const deployTransaction = await client.deployContract({
    code: contractCode,
    args,
  });

  const receipt = await client.waitForTransactionReceipt({
    hash: deployTransaction as TransactionHash,
    status: TransactionStatus.ACCEPTED,
    retries: 200,
  });

  if (
    receipt.status !== 5 &&
    receipt.status !== 6 &&
    receipt.statusName !== "ACCEPTED" &&
    receipt.statusName !== "FINALIZED"
  ) {
    throw new Error(`Deployment failed for ${relativePath}. Receipt: ${JSON.stringify(receipt)}`);
  }

  const deployedContractAddress =
    (client.chain as GenLayerChain).id === localnet.id
      ? receipt.data.contract_address
      : (receipt.txDataDecoded as DecodedDeployData)?.contractAddress;

  console.log(`${relativePath} deployed at address: ${deployedContractAddress}`);
  return deployedContractAddress as string;
}

export default async function main(client: GenLayerClient<any>) {
  try {
    await client.initializeConsensusSmartContract();

    // Deploy order matters: RecoveryArbiter's constructor takes
    // SignatureVerifier's address (the signature-verification logic was
    // extracted into its own contract purely to clear Bradbury's
    // undocumented ~20-22KB deploy gas ceiling - see
    // contracts/signature_verifier.py's docstring and genvm-manager#46),
    // and RecoveryReleaseVault's constructor takes RecoveryArbiter's.
    const verifierAddress = await deployOne(client, "contracts/signature_verifier.py", []);
    const arbiterAddress = await deployOne(client, "contracts/recovery_arbiter.py", [verifierAddress]);
    const vaultAddress = await deployOne(client, "contracts/recovery_release_vault.py", [arbiterAddress]);

    console.log(
      `\nDeployed:\n  SignatureVerifier:    ${verifierAddress}\n  RecoveryArbiter:      ${arbiterAddress}\n  RecoveryReleaseVault: ${vaultAddress}`
    );
  } catch (error) {
    throw new Error(`Error during deployment:, ${error}`);
  }
}
