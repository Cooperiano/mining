#!/usr/bin/env python3
"""
盈利分析工具 - 为Agent提供投资决策支持
"""

from __future__ import annotations
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any
from dataclasses import dataclass

@dataclass
class ProfitabilityMetrics:
    """盈利指标"""
    gpu_model: str
    expected_hashrate_th: float
    rental_cost_per_hour: float
    electricity_cost_per_hour: float
    total_cost_per_hour: float  # 总成本
    revenue_per_hour: float
    net_profit_per_hour: float
    roi_hours: float
    profitability_score: float
    recommendation: str  # "BUY", "HOLD", "SKIP"

class ProfitabilityTools:
    """盈利分析工具集"""

    # GPU参考算力（TH/s）
    GPU_HASHRATES = {
        "rtx_5090": 300,
        "rtx_5080": 185,
        "rtx_5070_ti": 150,
        "rtx_4090": 240,
        "rtx_3090": 110,
        "rtx_3080": 90,
        "rtx_3070": 70,
        "rtx_3060_ti": 65,
        "rtx_3060": 25,
        "rtx_4060_ti": 68,
        "rtx_4070": 100,
        "h100": 620,
        "h200": 650,
    }

    # 挖矿参数
    EARN_RATE = 3.226  # PRL per TH/s per day
    DEFAULT_PRL_PRICE = 0.21  # USD

    def __init__(self, wallet: str = "prl1pyvv3nzlvyahzgdhsg4c4sm3z6ukv9zcc39genld24yw4thmet6asevn44h"):
        self.wallet = wallet
        self.api_url = f"https://pearl.alphapool.tech/api/miner/{wallet}"

    def get_current_prl_price(self) -> Dict[str, Any]:
        """获取当前PRL价格"""

        try:
            # 这里可以从多个API获取价格
            # 简化版本使用固定价格
            return {
                "price": self.DEFAULT_PRL_PRICE,
                "source": "fixed",
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            print(f"获取PRL价格失败: {e}")
            return {
                "price": self.DEFAULT_PRL_PRICE,
                "source": "fallback",
                "error": str(e)
            }

    def calculate_revenue_per_hour(
        self,
        hashrate_th: float,
        prl_price: float | None = None
    ) -> float:
        """计算每小时收益"""

        if prl_price is None:
            prl_price = self.DEFAULT_PRL_PRICE

        return (hashrate_th / 1000) * self.EARN_RATE * prl_price

    def calculate_profitability(
        self,
        gpu_model: str,
        rental_price_per_hour: float,
        prl_price: float | None = None,
        electricity_watts: float = 0,
        electricity_cost_usd_per_kwh: float = 0.122
    ) -> ProfitabilityMetrics:
        """计算GPU盈利能力"""

        if prl_price is None:
            prl_price = self.DEFAULT_PRL_PRICE

        # 获取预期算力
        gpu_key = gpu_model.lower().replace(" ", "_").replace("nvidia", "").strip("_")
        expected_hashrate = float(self.GPU_HASHRATES.get(gpu_key, 200))

        # 计算收益
        revenue_per_hour = self.calculate_revenue_per_hour(expected_hashrate, prl_price)

        # 计算成本
        electricity_cost_per_hour = (electricity_watts / 1000) * electricity_cost_usd_per_kwh
        total_cost_per_hour = rental_price_per_hour + electricity_cost_per_hour

        # 计算净利润
        net_profit_per_hour = revenue_per_hour - total_cost_per_hour

        # 计算ROI时间（小时）
        roi_hours = total_cost_per_hour / net_profit_per_hour if net_profit_per_hour > 0 else float('inf')

        # 计算盈利评分
        if net_profit_per_hour > 0:
            profitability_score = min(100, (net_profit_per_hour / expected_hashrate) * 100)
        else:
            profitability_score = 0

        # 生成建议
        if net_profit_per_hour > 0.10:  # 每小时净利润超过10美分
            recommendation = "BUY"
        elif net_profit_per_hour > 0:
            recommendation = "HOLD"
        else:
            recommendation = "SKIP"

        return ProfitabilityMetrics(
            gpu_model=gpu_model,
            expected_hashrate_th=expected_hashrate,
            rental_cost_per_hour=rental_price_per_hour,
            electricity_cost_per_hour=electricity_cost_per_hour,
            total_cost_per_hour=total_cost_per_hour,
            revenue_per_hour=revenue_per_hour,
            net_profit_per_hour=net_profit_per_hour,
            roi_hours=roi_hours,
            profitability_score=profitability_score,
            recommendation=recommendation
        )

    def analyze_investment_opportunity(
        self,
        gpu_model: str,
        rental_price: float,
        investment_hours: int = 24
    ) -> Dict[str, Any]:
        """分析投资机会"""

        prl_data = self.get_current_prl_price()
        current_prl_price = prl_data["price"]

        profitability = self.calculate_profitability(
            gpu_model, rental_price, current_prl_price
        )

        # 计算投资周期收益
        total_revenue = profitability.revenue_per_hour * investment_hours
        total_cost = profitability.total_cost_per_hour * investment_hours
        total_profit = total_revenue - total_cost

        return {
            "gpu_model": gpu_model,
            "rental_price_per_hour": rental_price,
            "current_prl_price": current_prl_price,
            "expected_hashrate_th": profitability.expected_hashrate_th,
            "revenue_per_hour": profitability.revenue_per_hour,
            "cost_per_hour": profitability.total_cost_per_hour,
            "net_profit_per_hour": profitability.net_profit_per_hour,
            "roi_hours": profitability.roi_hours,
            "profitability_score": profitability.profitability_score,
            "recommendation": profitability.recommendation,
            "investment_projection": {
                "hours": investment_hours,
                "total_revenue": total_revenue,
                "total_cost": total_cost,
                "total_profit": total_profit,
                "roi_percentage": (total_profit / total_cost * 100) if total_cost > 0 else 0
            },
            "risk_assessment": self.assess_risk(profitability),
            "timestamp": datetime.now().isoformat()
        }

    def assess_risk(self, profitability: ProfitabilityMetrics) -> Dict[str, Any]:
        """评估投资风险"""

        risk_factors = []
        risk_level = "LOW"

        # 检查净利润率
        profit_margin = profitability.net_profit_per_hour / profitability.revenue_per_hour if profitability.revenue_per_hour > 0 else 0

        if profit_margin < 0.1:  # 净利润率低于10%
            risk_factors.append("低利润率")
            risk_level = "HIGH"

        # 检查ROI时间
        if profitability.roi_hours > 48:  # ROI超过48小时
            risk_factors.append("长ROI周期")
            if risk_level == "LOW":
                risk_level = "MEDIUM"

        # 检查GPU型号
        if "5090" not in profitability.gpu_model.lower():
            risk_factors.append("非旗舰GPU")
            if risk_level == "LOW":
                risk_level = "MEDIUM"

        return {
            "level": risk_level,
            "factors": risk_factors,
            "profit_margin": profit_margin,
            "roi_hours": profitability.roi_hours
        }

    def compare_opportunities(
        self,
        opportunities: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """比较多个投资机会"""

        analyzed = []

        for opp in opportunities:
            try:
                analysis = self.analyze_investment_opportunity(
                    opp.get("gpu_model", "RTX_5090"),
                    opp.get("rental_price", 0.56),
                    opp.get("investment_hours", 24)
                )

                analyzed.append({
                    **opp,
                    "analysis": analysis
                })
            except Exception as e:
                print(f"分析机会失败: {e}")
                continue

        # 按盈利能力排序
        analyzed.sort(
            key=lambda x: x["analysis"]["net_profit_per_hour"],
            reverse=True
        )

        return analyzed

    def get_portfolio_recommendation(
        self,
        budget_usd: float,
        max_instances: int = 10,
        min_profitability_score: float = 50
    ) -> Dict[str, Any]:
        """获取投资组合建议"""

        # 这里应该结合市场数据生成最优组合
        # 简化版本返回基础建议

        return {
            "strategy": "conservative",  # conservative, balanced, aggressive
            "recommended_instances": max_instances,
            "target_gpu_model": "RTX_5090",
            "max_rental_price": 0.56,
            "expected_daily_profit": budget_usd * 0.15,  # 期望15%日收益
            "risk_level": "MEDIUM",
            "diversification": "建议混合使用不同GPU型号以降低风险",
            "timestamp": datetime.now().isoformat()
        }