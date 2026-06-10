import os
import sys
from typing import Any, Dict

import structlog

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
                # If short, cover the short first. Any residual quantity opens a long position.
                if ticker in positions and positions[ticker]["shares"] < 0:
                    held_shares = abs(positions[ticker]["shares"])
                    avg_short_cost = positions[ticker]["total_cost"] / held_shares
                    
                    cover_qty = min(quantity, held_shares)
                    cover_cost = cover_qty * price
                    cash -= cover_cost
                    
                    trade_realized_pnl = cover_qty * (avg_short_cost - price)
                    realized_pnl += trade_realized_pnl
                    if trade_realized_pnl > 0.0:
                        closed_wins += 1
                    elif trade_realized_pnl < 0.0:
                        closed_losses += 1
                        
                    positions[ticker]["shares"] += cover_qty
                    positions[ticker]["total_cost"] = abs(positions[ticker]["shares"]) * avg_short_cost
                    
                    if positions[ticker]["shares"] == 0:
                        positions.pop(ticker)
                        
                    residual_qty = quantity - cover_qty
                    if residual_qty > 0:
                        cost = residual_qty * price
                        cash -= cost
                        positions[ticker] = {"shares": residual_qty, "total_cost": cost}
                else:
                    cost = quantity * price
                    cash -= cost
                    if ticker not in positions:
                        positions[ticker] = {"shares": 0, "total_cost": 0.0}
                    positions[ticker]["shares"] += quantity
                    positions[ticker]["total_cost"] += cost
            elif action == "sell":
                # If long, close the long first. Any residual quantity opens a short position.
                if ticker in positions and positions[ticker]["shares"] > 0:
                    held_shares = positions[ticker]["shares"]
                    avg_long_cost = positions[ticker]["total_cost"] / held_shares
                    
                    close_qty = min(quantity, held_shares)
                    proceeds = close_qty * price
                    cash += proceeds
                    
                    trade_realized_pnl = proceeds - (close_qty * avg_long_cost)
                    realized_pnl += trade_realized_pnl
                    if trade_realized_pnl > 0.0:
                        closed_wins += 1
                    elif trade_realized_pnl < 0.0:
                        closed_losses += 1
                        
                    positions[ticker]["shares"] -= close_qty
                    positions[ticker]["total_cost"] = positions[ticker]["shares"] * avg_long_cost
                    
                    if positions[ticker]["shares"] == 0:
                        positions.pop(ticker)
                        
                    residual_qty = quantity - close_qty
                    if residual_qty > 0:
                        proceeds = residual_qty * price
                        cash += proceeds
                        positions[ticker] = {"shares": -residual_qty, "total_cost": proceeds}
                else:
                    proceeds = quantity * price
                    cash += proceeds
                    if ticker not in positions:
                        positions[ticker] = {"shares": 0, "total_cost": 0.0}
                    positions[ticker]["shares"] -= quantity
                    positions[ticker]["total_cost"] += proceeds

        # 3. Enrich active positions with current market prices
        enriched_positions = []
        total_market_value = 0.0
        total_unrealized_pnl = 0.0

        for ticker, pos_data in positions.items():
            shares = pos_data["shares"]
            total_cost = pos_data["total_cost"]
            if shares > 0:
                avg_price = total_cost / shares
                current_price = await self.price_feed.get_price(ticker)
                market_value = shares * current_price
                unrealized_pnl = market_value - total_cost
            else:
                avg_price = total_cost / abs(shares) if shares < 0 else 0.0
                current_price = await self.price_feed.get_price(ticker)
                market_value = shares * current_price
                unrealized_pnl = total_cost + market_value
            
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

    async def get_portfolio_history(self) -> list:
        """
        Reconstructs the historical portfolio valuation and P&L path
        step-by-step for each transaction.
        """
        logger.info("Reconstructing historical portfolio P&L path...")
        raw_trades = await self.db.query_raw_trades()
        
        history = []
        
        # Add initial starting point
        history.append({
            "timestamp": "2026-06-01T00:00:00Z",
            "portfolio_value": float(settings.INITIAL_PORTFOLIO_CAPITAL),
            "cash": float(settings.INITIAL_PORTFOLIO_CAPITAL),
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "total_pnl": 0.0
        })
        
        cash = float(settings.INITIAL_PORTFOLIO_CAPITAL)
        positions = {}
        realized_pnl = 0.0
        
        for trade in raw_trades:
            ticker = trade["ticker"].strip().upper()
            action = trade["action"].lower()
            quantity = int(trade["quantity"])
            price = float(trade["price"])
            executed_at = trade["executed_at"]
            
            if action == "buy":
                # If short, cover the short first. Any residual quantity opens a long position.
                if ticker in positions and positions[ticker]["shares"] < 0:
                    held_shares = abs(positions[ticker]["shares"])
                    avg_short_cost = positions[ticker]["total_cost"] / held_shares
                    
                    cover_qty = min(quantity, held_shares)
                    cover_cost = cover_qty * price
                    cash -= cover_cost
                    
                    trade_realized_pnl = cover_qty * (avg_short_cost - price)
                    realized_pnl += trade_realized_pnl
                    
                    positions[ticker]["shares"] += cover_qty
                    positions[ticker]["total_cost"] = abs(positions[ticker]["shares"]) * avg_short_cost
                    positions[ticker]["last_price"] = price
                    
                    if positions[ticker]["shares"] == 0:
                        positions.pop(ticker)
                        
                    residual_qty = quantity - cover_qty
                    if residual_qty > 0:
                        cost = residual_qty * price
                        cash -= cost
                        positions[ticker] = {"shares": residual_qty, "total_cost": cost, "last_price": price}
                else:
                    cost = quantity * price
                    cash -= cost
                    if ticker not in positions:
                        positions[ticker] = {"shares": 0, "total_cost": 0.0, "last_price": price}
                    positions[ticker]["shares"] += quantity
                    positions[ticker]["total_cost"] += cost
                    positions[ticker]["last_price"] = price
            elif action == "sell":
                # If long, close the long first. Any residual quantity opens a short position.
                if ticker in positions and positions[ticker]["shares"] > 0:
                    held_shares = positions[ticker]["shares"]
                    avg_long_cost = positions[ticker]["total_cost"] / held_shares
                    
                    close_qty = min(quantity, held_shares)
                    proceeds = close_qty * price
                    cash += proceeds
                    
                    trade_realized_pnl = proceeds - (close_qty * avg_long_cost)
                    realized_pnl += trade_realized_pnl
                    
                    positions[ticker]["shares"] -= close_qty
                    positions[ticker]["total_cost"] = positions[ticker]["shares"] * avg_long_cost
                    positions[ticker]["last_price"] = price
                    
                    if positions[ticker]["shares"] == 0:
                        positions.pop(ticker)
                        
                    residual_qty = quantity - close_qty
                    if residual_qty > 0:
                        proceeds = residual_qty * price
                        cash += proceeds
                        positions[ticker] = {"shares": -residual_qty, "total_cost": proceeds, "last_price": price}
                else:
                    proceeds = quantity * price
                    cash += proceeds
                    if ticker not in positions:
                        positions[ticker] = {"shares": 0, "total_cost": 0.0, "last_price": price}
                    positions[ticker]["shares"] -= quantity
                    positions[ticker]["total_cost"] += proceeds
                    positions[ticker]["last_price"] = price
            
            # Recompute total position value and unrealized pnl
            positions_value = 0.0
            unrealized_pnl_val = 0.0
            for tk, pos in positions.items():
                sh = pos["shares"]
                mv = sh * pos["last_price"]
                positions_value += mv
                if sh >= 0:
                    unrealized_pnl_val += (mv - pos["total_cost"])
                else:
                    unrealized_pnl_val += (pos["total_cost"] + mv)
                
            step_val = cash + positions_value
            history.append({
                "timestamp": executed_at.isoformat() + "Z" if hasattr(executed_at, "isoformat") else str(executed_at),
                "portfolio_value": round(step_val, 2),
                "cash": round(cash, 2),
                "realized_pnl": round(realized_pnl, 2),
                "unrealized_pnl": round(unrealized_pnl_val, 2),
                "total_pnl": round(step_val - float(settings.INITIAL_PORTFOLIO_CAPITAL), 2)
            })
            
        return history
