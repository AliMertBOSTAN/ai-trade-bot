"""Minimal ABI parçaları - sadece kullandığımız fonksiyonlar."""

ERC20_ABI = [
    {"constant": True, "inputs": [], "name": "decimals",
     "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "symbol",
     "outputs": [{"name": "", "type": "string"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "owner", "type": "address"}],
     "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}],
     "type": "function"},
    {"constant": False, "inputs": [
        {"name": "spender", "type": "address"},
        {"name": "value", "type": "uint256"}],
     "name": "approve", "outputs": [{"name": "", "type": "bool"}],
     "type": "function"},
    {"constant": True, "inputs": [
        {"name": "owner", "type": "address"},
        {"name": "spender", "type": "address"}],
     "name": "allowance", "outputs": [{"name": "", "type": "uint256"}],
     "type": "function"},
]

# Uniswap/Pancake/QuickSwap V2 factory
V2_FACTORY_ABI = [
    {"constant": True, "inputs": [
        {"name": "tokenA", "type": "address"},
        {"name": "tokenB", "type": "address"}],
     "name": "getPair", "outputs": [{"name": "pair", "type": "address"}],
     "type": "function"},
]

# V2 pair
V2_PAIR_ABI = [
    {"constant": True, "inputs": [], "name": "getReserves", "outputs": [
        {"name": "_reserve0", "type": "uint112"},
        {"name": "_reserve1", "type": "uint112"},
        {"name": "_blockTimestampLast", "type": "uint32"}],
     "type": "function"},
    {"constant": True, "inputs": [], "name": "token0",
     "outputs": [{"name": "", "type": "address"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "token1",
     "outputs": [{"name": "", "type": "address"}], "type": "function"},
]

# V2 router (swap için)
V2_ROUTER_ABI = [
    {"name": "getAmountsOut", "stateMutability": "view", "type": "function",
     "inputs": [
        {"name": "amountIn", "type": "uint256"},
        {"name": "path", "type": "address[]"}],
     "outputs": [{"name": "amounts", "type": "uint256[]"}]},
    {"name": "swapExactTokensForTokens", "stateMutability": "nonpayable",
     "type": "function", "inputs": [
        {"name": "amountIn", "type": "uint256"},
        {"name": "amountOutMin", "type": "uint256"},
        {"name": "path", "type": "address[]"},
        {"name": "to", "type": "address"},
        {"name": "deadline", "type": "uint256"}],
     "outputs": [{"name": "amounts", "type": "uint256[]"}]},
]

# Uniswap V3 QuoterV2: quoteExactInputSingle (struct param)
V3_QUOTER_V2_ABI = [
    {"name": "quoteExactInputSingle", "stateMutability": "nonpayable",
     "type": "function",
     "inputs": [{"name": "params", "type": "tuple", "components": [
        {"name": "tokenIn", "type": "address"},
        {"name": "tokenOut", "type": "address"},
        {"name": "amountIn", "type": "uint256"},
        {"name": "fee", "type": "uint24"},
        {"name": "sqrtPriceLimitX96", "type": "uint160"}]}],
     "outputs": [
        {"name": "amountOut", "type": "uint256"},
        {"name": "sqrtPriceX96After", "type": "uint160"},
        {"name": "initializedTicksCrossed", "type": "uint32"},
        {"name": "gasEstimate", "type": "uint256"}]},
]

# Uniswap V3 SwapRouter02: exactInputSingle
V3_ROUTER_02_ABI = [
    {"name": "exactInputSingle", "stateMutability": "payable",
     "type": "function",
     "inputs": [{"name": "params", "type": "tuple", "components": [
        {"name": "tokenIn", "type": "address"},
        {"name": "tokenOut", "type": "address"},
        {"name": "fee", "type": "uint24"},
        {"name": "recipient", "type": "address"},
        {"name": "amountIn", "type": "uint256"},
        {"name": "amountOutMinimum", "type": "uint256"},
        {"name": "sqrtPriceLimitX96", "type": "uint160"}]}],
     "outputs": [{"name": "amountOut", "type": "uint256"}]},
]
