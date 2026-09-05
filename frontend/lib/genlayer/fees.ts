"use client";

export type FeePresetLevel = "low" | "standard" | "high";

export type FeePresetEstimate = {
  level: FeePresetLevel;
  estimate?: {
    distribution?: Record<string, unknown>;
    messageAllocations?: Record<string, unknown>[];
    feeValue?: bigint | number | string;
    fee_value?: bigint | number | string;
    observed?: Record<string, unknown>;
  };
  observed?: Record<string, unknown>;
};

const PRESET_OPTIONS: Record<FeePresetLevel, Record<string, unknown>> = {
  low: {
    appealRounds: 0n,
    rotations: [0n],
  },
  standard: {
    appealRounds: 1n,
    rotations: [0n, 0n],
  },
  high: {
    appealRounds: 2n,
    rotations: [0n, 0n, 0n],
  },
};

function transactionFeesFromEstimate(estimate: FeePresetEstimate["estimate"]) {
  if (!estimate?.distribution) return undefined;

  const fees: Record<string, unknown> = {
    distribution: estimate.distribution,
  };

  if (estimate.messageAllocations) {
    fees.messageAllocations = estimate.messageAllocations;
  }

  const feeValue = estimate.feeValue ?? estimate.fee_value;
  if (feeValue !== undefined) {
    fees.feeValue = feeValue;
  }

  return fees;
}

export function feePresetToTransactionFees(preset?: FeePresetEstimate) {
  return transactionFeesFromEstimate(preset?.estimate);
}

// Fee estimation simulates the write against the network before the real
// transaction is sent. If the network is slow/degraded, this simulate call
// can hang far longer than a user will wait, with no error and no tx hash
// ever appearing (the real write hasn't even been sent yet). A bounded
// timeout means a stuck estimate degrades to "submit with default fees"
// instead of silently blocking the whole submission forever.
const FEE_ESTIMATE_TIMEOUT_MS = 10_000;

async function estimateWriteFeePresetInner(
  client: any,
  request: {
    address: `0x${string}`;
    functionName: string;
    args: unknown[];
    value?: bigint;
  },
  level: FeePresetLevel,
): Promise<FeePresetEstimate | undefined> {
  const options = PRESET_OPTIONS[level];
  const initialEstimate = await client.estimateTransactionFees(options);
  let estimate = initialEstimate;

  if (
    typeof client.simulateWriteContract === "function" &&
    typeof client.estimateTransactionFeesFromSimulation === "function"
  ) {
    const simulation = await client.simulateWriteContract({
      ...request,
      includeReceipt: true,
      value: request.value ?? 0n,
      fees: transactionFeesFromEstimate(initialEstimate),
    });

    estimate = await client.estimateTransactionFeesFromSimulation({
      ...options,
      simulation,
    });
  }

  return {
    level,
    estimate,
    observed: estimate?.observed,
  };
}

export async function estimateWriteFeePreset(
  client: any,
  request: {
    address: `0x${string}`;
    functionName: string;
    args: unknown[];
    value?: bigint;
  },
  level: FeePresetLevel = "standard",
): Promise<FeePresetEstimate | undefined> {
  if (typeof client?.estimateTransactionFees !== "function") {
    return undefined;
  }

  try {
    return await new Promise<FeePresetEstimate | undefined>((resolve, reject) => {
      const timer = setTimeout(
        () => reject(new Error("Fee estimation timed out")),
        FEE_ESTIMATE_TIMEOUT_MS,
      );
      estimateWriteFeePresetInner(client, request, level).then(
        (value) => {
          clearTimeout(timer);
          resolve(value);
        },
        (err) => {
          clearTimeout(timer);
          reject(err);
        },
      );
    });
  } catch (err) {
    console.warn("Fee estimation failed or timed out, submitting with default fees:", err);
    return undefined;
  }
}
