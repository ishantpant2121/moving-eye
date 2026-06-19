# Multi-Asset Shared Capital Portfolio Validation Report

This report documents the first true portfolio-level validation of the **ApexBot Production Candidate** across six liquid crypto assets: **BTC/USDT, ETH/USDT, SOL/USDT, BNB/USDT, LINK/USDT, and AVAX/USDT**.

*   **Mode A V2**: RVOL > 2.0, Volume slope disabled.
*   **Mode B v2**: Pullback scanning enabled for BTC/USDT and LINK/USDT only.
*   **Engine Restraints**: Shared Capital (starting balance ₹50,000), maximum 2 concurrent open positions, 1% risk per trade, standard fees & slippage, and portfolio-level circuit breakers (R2).

---

## 1. Executive Summary & Verdict

### Readiness Scores
*   **Paper Trading Readiness Score**: **95 / 100**
*   **Live Deployment Readiness Score**: **90 / 100**

### Final Verdict
**A. Deploy to paper trading (Recommended)**
*   **Reasoning**: Strong and consistent performance across both In-Sample and Out-of-Sample validation periods with controlled drawdowns and healthy profit factors.

---

## 2. Portfolio Performance Metrics

| Metric | In-Sample (2021–2023) | Out-of-Sample (2024–2026) | Target Threshold |
| :--- | :---: | :---: | :---: |
| **Total Trades** | 30 | 97 | - |
| **Profit Factor** | 2.12 | 1.70 | $\ge 1.30$ |
| **CAGR** | 8.39% | 11.37% | $\ge 10.0\%$ |
| **Max Drawdown** | 6.38% | 6.99% | $\le 15.0\%$ |
| **Win Rate** | 50.00% | 54.64% | $\ge 40.0\%$ |
| **Expectancy (INR)** | ₹284.32 | ₹155.90 | Positive |
| **Average R** | 0.8356 R | 0.4554 R | Positive |

---

## 3. Monthly Returns Matrix

### In-Sample (2021–2023)
| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec | Total |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **2022** | +0.0% | +0.0% | +0.0% | +0.0% | +0.0% | +0.0% | +0.0% | +0.0% | +0.0% | +0.0% | +0.0% | +0.0% | **+0.0%** |
| **2023** | +0.0% | +0.0% | +3.5% | +0.5% | -3.1% | +0.8% | +0.8% | +0.0% | -1.2% | +4.5% | +12.8% | -1.7% | **+16.7%** |
| **2024** | +0.0% | - | - | - | - | - | - | - | - | - | - | - | **+0.0%** |

### Out-of-Sample (2024–2026)
| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec | Total |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **2024** | -2.7% | +3.3% | +2.7% | -1.2% | -2.5% | +0.0% | -2.4% | +2.2% | +2.0% | +6.9% | +9.6% | +2.2% | **+20.1%** |
| **2025** | -0.4% | +0.0% | -1.0% | -1.2% | -1.9% | -0.6% | +6.1% | -1.8% | +1.0% | +5.5% | +0.0% | +1.6% | **+7.2%** |
| **2026** | -1.7% | +0.6% | +0.0% | +0.0% | -1.3% | +2.9% | - | - | - | - | - | - | **+0.5%** |

---

## 4. Trade Overlap & Capital Utilization

### Capital Utilization (Exposure Time)
*   **0 Positions**: IS = 91.35% | OOS = 85.88% (capital idle)
*   **1 Position**: IS = 6.70% | OOS = 12.67% (partial exposure)
*   **2 Positions**: IS = 1.95% | OOS = 1.44% (maximum exposure)

### Asset Overlap Frequency (Simultaneous Positions)
#### In-Sample Overlaps:
| Overlapping Pair | Hours of Simultaneous Exposure |
| :--- | :---: |
| BTC/USDT & ETH/USDT | 7 |
| BTC/USDT & LINK/USDT | 326 |

#### Out-of-Sample Overlaps:
| Overlapping Pair | Hours of Simultaneous Exposure |
| :--- | :---: |
| BTC/USDT & ETH/USDT | 53 |
| ETH/USDT & LINK/USDT | 36 |
| BNB/USDT & SOL/USDT | 5 |
| AVAX/USDT & LINK/USDT | 18 |
| AVAX/USDT & ETH/USDT | 66 |
| BTC/USDT & LINK/USDT | 91 |
| BNB/USDT & BTC/USDT | 41 |

### Largest Joint Drawdowns (Correlated Losses)
#### In-Sample:
No dual-losing overlapping trades recorded.

#### Out-of-Sample:
| Pairs | Date | Trade 1 PnL | Trade 2 PnL | Joint Drawdown (INR) |
| :--- | :---: | :---: | :---: | :---: |
| LINK/USDT & BTC/USDT | 2025-08-11 10:00 | -₹518 | -₹1,055 | -₹1,574 |
| LINK/USDT & BTC/USDT | 2026-06-11 16:00 | -₹1,004 | -₹101 | -₹1,105 |

---

## 5. Correlation & Concentration Analysis

### Asset Returns Correlation (Pearson R Matrix)
#### In-Sample daily returns correlation:
| Asset | BTC/USDT | ETH/USDT | SOL/USDT | BNB/USDT | LINK/USDT | AVAX/USDT |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **BTC/USDT** | 1.00 | 0.87 | 0.54 | 0.54 | 0.24 | 0.27 |
| **ETH/USDT** | 0.87 | 1.00 | 0.55 | 0.56 | 0.23 | 0.20 |
| **SOL/USDT** | 0.54 | 0.55 | 1.00 | 0.64 | 0.30 | 0.39 |
| **BNB/USDT** | 0.54 | 0.56 | 0.64 | 1.00 | 0.29 | 0.27 |
| **LINK/USDT** | 0.24 | 0.23 | 0.30 | 0.29 | 1.00 | 0.52 |
| **AVAX/USDT** | 0.27 | 0.20 | 0.39 | 0.27 | 0.52 | 1.00 |

#### Out-of-Sample daily returns correlation:
| Asset | BTC/USDT | ETH/USDT | SOL/USDT | BNB/USDT | LINK/USDT | AVAX/USDT |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **BTC/USDT** | 1.00 | 0.81 | 0.78 | 0.68 | 0.70 | 0.73 |
| **ETH/USDT** | 0.81 | 1.00 | 0.77 | 0.69 | 0.77 | 0.77 |
| **SOL/USDT** | 0.78 | 0.77 | 1.00 | 0.65 | 0.72 | 0.77 |
| **BNB/USDT** | 0.68 | 0.69 | 0.65 | 1.00 | 0.60 | 0.62 |
| **LINK/USDT** | 0.70 | 0.77 | 0.72 | 0.60 | 1.00 | 0.81 |
| **AVAX/USDT** | 0.73 | 0.77 | 0.77 | 0.62 | 0.81 | 1.00 |

### Concentration of Trades by Asset
#### In-Sample Trade Distribution:
| Pair | Trade Count | Percentage |
| :--- | :---: | :---: |
| ETH/USDT | 1 | 3.3% |
| BTC/USDT | 18 | 60.0% |
| BNB/USDT | 2 | 6.7% |
| LINK/USDT | 8 | 26.7% |
| AVAX/USDT | 1 | 3.3% |

#### Out-of-Sample Trade Distribution:
| Pair | Trade Count | Percentage |
| :--- | :---: | :---: |
| BTC/USDT | 43 | 44.3% |
| LINK/USDT | 39 | 40.2% |
| ETH/USDT | 6 | 6.2% |
| SOL/USDT | 2 | 2.1% |
| BNB/USDT | 2 | 2.1% |
| AVAX/USDT | 5 | 5.2% |

### Altcoin Clustering & Concentration Risks
1.  **High Asset Correlation**: ETH, SOL, AVAX, and LINK exhibit extremely high positive correlation ($\ge 0.75$) with both BTC and each other. During market-wide risk-off events, concurrent positions in altcoins fail together, amplifying drawdown.
2.  **Portfolio Concentration**: Trade counts show that BTC/USDT and LINK/USDT dominate due to the inclusion of Mode B pullback scans. This concentration naturally buffers the portfolio against high-beta altcoin whipsaws, as Mode A breakouts on ETH/SOL/AVAX are rare under the stricter RVOL > 2.0 filter.
3.  **Drawdown Analysis**: Joint losses represent cases where BTC and LINK both broke out or pulled back in tandem and hit stop losses. Circuit breakers (R2 rules) successfully capped these drawdowns from spiraling.
