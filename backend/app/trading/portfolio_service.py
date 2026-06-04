from typing import Any, Dict, List
import structlog
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import settings
from app.database import ClickHouseDatabase
from app.trading.price_feed import PriceFeed

logger = structlog.get_logger()

class PortfolioService:
    def __init__(self, db: ClickHouseDatabase, price_feed: PriceFeed):
        self.db = db
        self.price_feed = price_feed

    async def reconstruct_portfolio(self) -> Dict[str, Any]:
        """
        Reconstructs the portfolio state (cash, positions, P&L, win rate)
        sequentially by iterating through all historical trades in ClickHouse.
        """
        logger.info("Reconstructing portfolio state from ClickHouse trades...")
        
        # 1. Fetch raw trade records from database
        raw_trades = await self.db.query_raw_trades()
        
        # 2. Sequential ledger reconstruction
        cash = float(settings.INITIAL_PORTFOLIO_CAPITAL)
        # ticker -> {"shares": int, "total_cost": float}
        positions: Dict[str, Dict[str, Any]] = {}
        
        realized_pnl = 0.0
        closed_wins = 0
        closed_losses = 0
        total_trades = len(raw_trades)

        for trade in raw_trades:
            ticker = trade["ticker"].strip().upper()
            action = trade["action"].lower()
            quantity = int(trade["quantity"])
            price = float(trade["price"])

            if action == "buy":
                cost = quantity * price
                cash -= cost
                if ticker not in positions:
                    positions[ticker] = {"shares": 0, "total_cost": 0.0}
                positions[ticker]["shares"] += quantity
                positions[ticker]["total_cost"] += cost
            elif action == "sell":
                # For long-only strategy liquidation, sell closes existing shares
                if ticker in positions and positions[ticker]["shares"] > 0:
                    held_shares = positions[ticker]["shares"]
                    avg_cost_per_share = positions[ticker]["total_cost"] / held_shares
                    
                    # Liquidate either the specified quantity or all held shares (fully close position)
                    sell_qty = min(quantity, held_shares)
                    proceeds = sell_qty * price
                    cash += proceeds
                    
                    # Calculate realized P&L based on cost basis
                    trade_cost_basis = sell_qty * avg_cost_per_share
                    trade_realized_pnl = proceeds - trade_cost_basis
                    realized_pnl += trade_realized_pnl
                    
                    if trade_realized_pnl > 0.0:
                        closed_wins += 1
                    elif trade_realized_pnl < 0.0:
                        closed_losses += 1

                    # Update position shares
                    positions[ticker]["shares"] -= sell_qty
                    positions[ticker]["total_cost"] -= trade_cost_basis
                    
                    # Clean up empty position
                    if positions[ticker]["shares"] <= 0:
                        positions.pop(ticker)
                else:
                    # Flat position, ignores sell or logs warning
                    logger.warning("Sell trade encountered on flat position", ticker=ticker, quantity=quantity, price=price)

        # 3. Enrich active positions with current market prices
        enriched_positions = []
        total_market_value = 0.0
        total_unrealized_pnl = 0.0

        for ticker, pos_data in positions.items():
            shares = pos_data["shares"]
            total_cost = pos_data["total_cost"]
            avg_price = total_cost / shares if shares > 0 else 0.0
            
            # Fetch current quote (hits cache/API)
            current_price = await self.price_feed.get_price(ticker)
            market_value = shares * current_price
            unrealized_pnl = market_value - total_cost
            
            total_market_value += market_value
            total_unrealized_pnl += unrealized_pnl

            enriched_positions.append({
                "ticker": ticker,
                "shares": shares,
                "avg_price": round(avg_price, 2),
                "current_price": round(current_price, 2),
                "market_value": round(market_value, 2),
                "unrealized_pnl": round(unrealized_pnl, 2)
            })

        # Calculate win rate
        total_closed_trades = closed_wins + closed_losses
        win_rate = float(closed_wins) / total_closed_trades if total_closed_trades > 0 else 0.0
        
        portfolio_value = cash + total_market_value

        state = {
            "portfolio_value_usd": round(portfolio_value, 2),
            "cash_usd": round(cash, 2),
            "unrealized_pnl_usd": round(total_unrealized_pnl, 2),
            "realized_pnl_usd": round(realized_pnl, 2),
            "total_pnl_usd": round(realized_pnl + total_unrealized_pnl, 2),
            "win_rate": round(win_rate, 2),
            "total_trades": total_trades,
            "positions": enriched_positions
        }

        logger.info(
            "Portfolio reconstruction complete",
            value=state["portfolio_value_usd"],
            cash=state["cash_usd"],
            positions_count=len(enriched_positions),
            realized_pnl=state["realized_pnl_usd"],
            win_rate=state["win_rate"]
        )
        return state
