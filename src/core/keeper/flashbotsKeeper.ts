// ============================================================
//  Ethers.js tabanlı Keeper - ArbExecutor kontratına MEV-korumalı
//  (Flashbots Protect) işlem gönderir.
//
//  Bu modül, Python engine bir arbitraj fırsatı onayladığında çağrılır.
//  TypeScript/Ethers.js katmanı şu Risk Controls'ü uygular:
//   1. callStatic ön-uçuş: tx zincire gitmeden simüle edilir; revert ederse
//      hiç gönderilmez (gas bile harcanmaz).
//   2. Gas tavanı: maxFeePerGas hesaplanan tavanı aşarsa iptal.
//   3. Flashbots Protect RPC: tx public mempool yerine private relay'e gider;
//      sandwich/front-running MEV saldırıları engellenir.
// ============================================================
import { ethers } from 'ethers'

// ETH mainnet için Flashbots Protect RPC (private mempool).
// Diğer zincirlerde MEV-Share / MEV-Blocker eşdeğerleri kullanılabilir.
const FLASHBOTS_PROTECT_RPC = 'https://rpc.flashbots.net/fast'

const ARB_EXECUTOR_ABI = [
  'function executeArb(address baseToken,uint256 amountIn,(address router,address[] path,uint256 amountOutMin) buyLeg,(address router,address[] path,uint256 amountOutMin) sellLeg,uint256 minProfit,uint256 deadline) external'
]

export interface Leg {
  router: string
  path: string[]
  amountOutMin: bigint
}

export interface ArbParams {
  baseToken: string
  amountIn: bigint
  buyLeg: Leg
  sellLeg: Leg
  minProfit: bigint
  deadlineSec: number
}

export interface KeeperConfig {
  executorAddress: string
  privateKey: string
  maxGasGwei: number
  useFlashbots: boolean
  /** standart RPC (okuma + non-mainnet gönderim) */
  rpcUrl: string
}

export class FlashbotsKeeper {
  private wallet: ethers.Wallet
  private readProvider: ethers.JsonRpcProvider
  private sendProvider: ethers.JsonRpcProvider
  private executor: ethers.Contract

  constructor(private cfg: KeeperConfig) {
    this.readProvider = new ethers.JsonRpcProvider(cfg.rpcUrl)
    // Gönderim: Flashbots Protect (MEV koruması) veya normal RPC
    this.sendProvider = cfg.useFlashbots
      ? new ethers.JsonRpcProvider(FLASHBOTS_PROTECT_RPC)
      : this.readProvider
    this.wallet = new ethers.Wallet(cfg.privateKey, this.sendProvider)
    this.executor = new ethers.Contract(cfg.executorAddress, ARB_EXECUTOR_ABI, this.wallet)
  }

  /**
   * Arbitrajı çalıştırır. Sırayla: gas kontrolü -> static ön-uçuş ->
   * MEV-korumalı gönderim -> receipt. Her aşamada başarısızlık net döner.
   */
  async execute(p: ArbParams): Promise<{ ok: boolean; txHash?: string; reason?: string }> {
    const deadline = BigInt(Math.floor(Date.now() / 1000) + p.deadlineSec)
    const args = [
      p.baseToken,
      p.amountIn,
      [p.buyLeg.router, p.buyLeg.path, p.buyLeg.amountOutMin],
      [p.sellLeg.router, p.sellLeg.path, p.sellLeg.amountOutMin],
      p.minProfit,
      deadline
    ] as const

    // 1) Gas tavanı
    const fee = await this.readProvider.getFeeData()
    const gwei = Number(ethers.formatUnits(fee.maxFeePerGas ?? fee.gasPrice ?? 0n, 'gwei'))
    if (gwei > this.cfg.maxGasGwei) {
      return { ok: false, reason: `Gas ${gwei.toFixed(1)} gwei > tavan ${this.cfg.maxGasGwei}` }
    }

    // 2) Static ön-uçuş: revert ederse hiç göndermeyiz (revert-on-no-profit dahil)
    try {
      await this.executor.executeArb.staticCall(...args)
    } catch (e: unknown) {
      return { ok: false, reason: `Ön-uçuş revert: ${(e as Error).message}` }
    }

    // 3) MEV-korumalı gönderim
    try {
      const tx = await this.executor.executeArb(...args, {
        maxFeePerGas: fee.maxFeePerGas ?? undefined,
        maxPriorityFeePerGas: fee.maxPriorityFeePerGas ?? undefined
      })
      const receipt = await tx.wait(1)
      if (!receipt || receipt.status !== 1) {
        return { ok: false, txHash: tx.hash, reason: 'Tx revert oldu' }
      }
      return { ok: true, txHash: tx.hash }
    } catch (e: unknown) {
      return { ok: false, reason: `Gönderim hatası: ${(e as Error).message}` }
    }
  }
}
