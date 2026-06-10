// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title ArbExecutor
 * @notice Aynı blokta atomik (tek transaction) iki-bacaklı DEX arbitrajı yürütür.
 *
 *  Risk Controls (kritik):
 *   - ATOMİKLİK: İki swap tek tx içinde. İkinci bacak başarısız olursa TÜM
 *     işlem revert olur; "yarım" pozisyonda kalınmaz.
 *   - REVERT-ON-NO-PROFIT: İşlem sonunda elde edilen miktar minProfit eşiğini
 *     karşılamıyorsa `Unprofitable()` ile revert edilir. Kâr garantisi
 *     on-chain zorunlu kılınır, off-chain tahmine güvenilmez.
 *   - SLIPPAGE GUARD: Her swap'a amountOutMin geçilir; router slippage'ı
 *     aşarsa kendi içinde revert eder.
 *   - DEADLINE: Router çağrılarına deadline verilir; tx mempool'da beklerse
 *     kötü fiyatla dolmaz.
 *   - OWNER-ONLY + REENTRANCY GUARD: Yalnızca sahibi tetikler, reentrancy kapalı.
 *
 *  MEV/Sandwich koruması bu kontratta değil, GÖNDERİM katmanındadır:
 *  tx'i public mempool yerine Flashbots Protect / private bundle ile
 *  göndermek sandwich saldırılarını engeller (bkz. README ve ts keeper).
 */

interface IERC20 {
    function approve(address spender, uint256 value) external returns (bool);
    function transfer(address to, uint256 value) external returns (bool);
    function transferFrom(address from, address to, uint256 value) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
}

/// Uniswap/Pancake/QuickSwap V2 uyumlu router
interface IV2Router {
    function swapExactTokensForTokens(
        uint256 amountIn,
        uint256 amountOutMin,
        address[] calldata path,
        address to,
        uint256 deadline
    ) external returns (uint256[] memory amounts);
}

contract ArbExecutor {
    address public owner;
    uint256 private _locked = 1;

    error NotOwner();
    error Reentrancy();
    error Unprofitable(uint256 got, uint256 required);
    error ZeroAddress();

    event ArbExecuted(
        address indexed token,
        uint256 amountIn,
        uint256 amountOut,
        uint256 profit
    );

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    modifier nonReentrant() {
        if (_locked != 1) revert Reentrancy();
        _locked = 2;
        _;
        _locked = 1;
    }

    constructor() {
        owner = msg.sender;
    }

    function setOwner(address newOwner) external onlyOwner {
        if (newOwner == address(0)) revert ZeroAddress();
        owner = newOwner;
    }

    struct Leg {
        address router;        // V2 uyumlu router
        address[] path;        // örn. [USDC, WETH] / [WETH, USDC]
        uint256 amountOutMin;  // slippage guard (off-chain quote'tan türetilir)
    }

    /**
     * @notice İki-bacaklı atomik arbitraj.
     * @param baseToken     başlangıç & bitiş token'ı (örn. USDC). Kâr bu cinsten.
     * @param amountIn      ilk bacağa girilen baseToken miktarı
     * @param buyLeg        ucuz DEX'te baseToken -> hedef token
     * @param sellLeg       pahalı DEX'te hedef token -> baseToken
     * @param minProfit     net minimum kâr (baseToken). Sağlanmazsa revert.
     * @param deadline      her iki swap için son geçerlilik zamanı
     */
    function executeArb(
        address baseToken,
        uint256 amountIn,
        Leg calldata buyLeg,
        Leg calldata sellLeg,
        uint256 minProfit,
        uint256 deadline
    ) external onlyOwner nonReentrant {
        IERC20 base = IERC20(baseToken);

        // sahipten sermayeyi çek
        require(base.transferFrom(msg.sender, address(this), amountIn), "pull failed");

        uint256 startBal = base.balanceOf(address(this));

        // --- 1. bacak: baseToken -> hedef token (ucuz DEX) ---
        base.approve(buyLeg.router, amountIn);
        uint256[] memory out1 = IV2Router(buyLeg.router).swapExactTokensForTokens(
            amountIn, buyLeg.amountOutMin, buyLeg.path, address(this), deadline
        );
        uint256 midAmount = out1[out1.length - 1];

        // --- 2. bacak: hedef token -> baseToken (pahalı DEX) ---
        address midToken = buyLeg.path[buyLeg.path.length - 1];
        IERC20(midToken).approve(sellLeg.router, midAmount);
        uint256[] memory out2 = IV2Router(sellLeg.router).swapExactTokensForTokens(
            midAmount, sellLeg.amountOutMin, sellLeg.path, address(this), deadline
        );

        uint256 endBal = base.balanceOf(address(this));

        // --- REVERT-ON-NO-PROFIT ---
        // Net kâr yeterli değilse tüm tx geri alınır; gas dışında kayıp olmaz.
        uint256 profit = endBal > startBal ? endBal - startBal : 0;
        if (profit < minProfit) revert Unprofitable(profit, minProfit);

        // sermaye + kârı sahibe iade et
        require(base.transfer(owner, endBal), "payout failed");

        emit ArbExecuted(baseToken, amountIn, out2[out2.length - 1], profit);
    }

    /// Acil durumda kalan token'ı kurtar (owner-only).
    function rescue(address token) external onlyOwner {
        IERC20 t = IERC20(token);
        t.transfer(owner, t.balanceOf(address(this)));
    }
}
