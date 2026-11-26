# Research methods and design

## What AI Hero contributes

AI Hero's skills are an engineering workflow, not a source of trading signals. The useful ideas here are to agree on the problem before implementation, keep a shared domain vocabulary, use tight test feedback loops, and put complex behavior behind small interfaces. The `TradingPolicy` seam accepts market data and a portfolio snapshot and returns a risk-sized decision. The same `MultiAgentResearchPolicy` is called by paper mode and the OOS simulator.

The TradingAgents paper is a design reference for specialized roles and structured bull/bear debate. This repository does not reproduce its LLM agents, data sources, training setup, or evaluation, so its reported results are not evidence for this project's policy.

## What the current replay does and does not establish

- `multi_agent` uses predictive direction plus context alignment. Volatility controls the ATR stop-distance size; debate is explanatory only, since the agents use correlated heuristic inputs. Historical sentiment is excluded because there is no timestamped sentiment dataset.
- Each fold is chronological; features use information available through the current close; simulated orders fill at the next bar's open with configured spread, slippage, and commission.
- The policy is fixed across folds and is compared with buy-and-hold and cash. The legacy `state_evaluator` path tunes its small parameter grid on the in-sample window only.
- The policy is long/flat. Position notional is sized from maximum per-trade risk divided by stop distance, capped by asset weight, portfolio exposure, and available cash. Daily/weekly loss limits and a drawdown liquidation are shared by research and paper mode.
- The paper runner adds a cross-asset portfolio-risk gate; the current validator is single-symbol and cannot validate portfolio correlation, VaR, or allocation across assets. Paper orders execute at current quotes, while OOS fills use next-bar opens. Protective stops are polled in paper mode, not hosted by an exchange. MCTS remains a dashboard experiment, not part of this policy.
- Synthetic data verifies mechanics only. No real-market performance claim is supported until a genuine chronological dataset is supplied and the assumptions are reviewed.

The policy's confidence field is a heuristic score, not a calibrated win probability. The old online `SelfLearningCritic` and its mutable parameters are not connected to the paper decision path; changing thresholds or sizing based on the same trades would introduce selection bias.

`agents.risk_manager.RiskManager` is retained for compatibility with older scripts, but it is not the risk engine used by the paper runner, dashboard policy preview, or walk-forward policy.

Walk-forward separation reduces direct look-ahead but does not correct for trying many ideas and selecting the best result. The current reports do not calculate the Probability of Backtest Overfitting (PBO), Combinatorially Symmetric Cross-Validation (CSCV), or the Deflated Sharpe Ratio (DSR). Record the number of strategies and parameter variants tried, and add selection-bias analysis before making performance claims.

## Sources

- AI Hero, [Skills for Real Engineers](https://www.aihero.dev/skills) and its [first-party skills repository](https://github.com/mattpocock/skills): alignment, shared vocabulary, test feedback, and module design practices.
- Yang et al., [TradingAgents: Multi-Agents LLM Financial Trading Framework](https://arxiv.org/abs/2412.20138): specialized roles and structured debate as a system-design reference, not a result transferable to this implementation.
- Bailey et al., [The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf): describes PBO and CSCV for assessing strategy-selection overfitting.
- Bailey and López de Prado, [The Deflated Sharpe Ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf): adjusts Sharpe inference for selection bias, sample length, and non-normal returns.
