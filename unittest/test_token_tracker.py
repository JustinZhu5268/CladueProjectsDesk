"""
Unit tests for TokenTracker - PRD v3 cost calculation and tracking
"""
import unittest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.token_tracker import TokenTracker, UsageInfo
from config import (
    CACHE_WRITE_MULTIPLIER_5M,
    CACHE_WRITE_MULTIPLIER_1H,
    CACHE_READ_MULTIPLIER,
    MODELS,
)


class TestUsageInfo(unittest.TestCase):
    """测试 UsageInfo 数据类"""
    
    def test_total_input_calculation(self):
        """测试总输入 token 计算"""
        usage = UsageInfo(
            input_tokens=1000,
            output_tokens=500,
            cache_creation_tokens=200,
            cache_read_tokens=800,
        )
        
        # total_input = input + cache_creation + cache_read
        self.assertEqual(usage.total_input, 2000)
    
    def test_to_dict(self):
        """测试转换为字典"""
        usage = UsageInfo(
            input_tokens=1000,
            output_tokens=500,
            cache_creation_tokens=200,
            cache_read_tokens=800,
        )
        
        d = usage.to_dict()
        
        self.assertEqual(d["input_tokens"], 1000)
        self.assertEqual(d["output_tokens"], 500)
        self.assertEqual(d["cache_creation_tokens"], 200)
        self.assertEqual(d["cache_read_tokens"], 800)
    
    def test_default_values(self):
        """测试默认值"""
        usage = UsageInfo()
        
        self.assertEqual(usage.input_tokens, 0)
        self.assertEqual(usage.output_tokens, 0)
        self.assertEqual(usage.cache_creation_tokens, 0)
        self.assertEqual(usage.cache_read_tokens, 0)


class TestTokenTrackerCostCalculation(unittest.TestCase):
    """测试 TokenTracker 成本计算"""
    
    def test_calculate_cost_with_cache_5m(self):
        """测试使用 5 分钟缓存的成本计算"""
        tracker = TokenTracker(cache_ttl="5m")
        
        usage = UsageInfo(
            input_tokens=1000,
            output_tokens=500,
            cache_creation_tokens=50000,  # 50K 缓存写入
            cache_read_tokens=45000,       # 45K 缓存读取
        )
        
        cost = tracker.calculate_cost("claude-sonnet-4-5-20250929", usage)
        
        # 验证成本计算正确
        # input: 1000 * $3/1M = $0.003
        # output: 500 * $15/1M = $0.0075
        # cache_write: 50000 * $3/1M * 1.25 = $0.1875
        # cache_read: 45000 * $3/1M * 0.1 = $0.0135
        expected = 0.003 + 0.0075 + 0.1875 + 0.0135
        self.assertAlmostEqual(cost, expected, places=4)
    
    def test_calculate_cost_with_cache_1h(self):
        """测试使用 1 小时缓存的成本计算"""
        tracker = TokenTracker(cache_ttl="1h")
        
        usage = UsageInfo(
            input_tokens=1000,
            output_tokens=500,
            cache_creation_tokens=50000,
            cache_read_tokens=45000,
        )
        
        cost = tracker.calculate_cost("claude-sonnet-4-5-20250929", usage)
        
        # cache_write: 50000 * $3/1M * 2.0 = $0.30
        expected = 0.003 + 0.0075 + 0.30 + 0.0135
        self.assertAlmostEqual(cost, expected, places=4)
    
    def test_calculate_cost_unknown_model(self):
        """测试使用未知模型时的回退"""
        tracker = TokenTracker()
        
        usage = UsageInfo(input_tokens=1000, output_tokens=500)
        
        # 未知模型应该回退到 Sonnet 定价
        cost = tracker.calculate_cost("unknown-model", usage)
        
        # 使用 Sonnet 定价: 1000*3/1M + 500*15/1M = 0.003 + 0.0075 = 0.0105
        self.assertAlmostEqual(cost, 0.0105, places=4)
    
    def test_cache_ttl_switch(self):
        """测试缓存 TTL 切换"""
        tracker = TokenTracker(cache_ttl="5m")
        
        usage = UsageInfo(
            input_tokens=0,
            output_tokens=0,
            cache_creation_tokens=10000,
        )
        
        cost_5m = tracker.calculate_cost("claude-sonnet-4-5-20250929", usage)
        
        # 切换到 1h
        tracker.cache_ttl = "1h"
        cost_1h = tracker.calculate_cost("claude-sonnet-4-5-20250929", usage)
        
        # 1h 的写入成本应该是 5m 的 1.6 倍 (2.0/1.25)
        self.assertAlmostEqual(cost_1h / cost_5m, 1.6, places=1)


class TestTokenTrackerEstimate(unittest.TestCase):
    """测试 TokenTracker 预估功能"""
    
    def test_estimate_input_cost(self):
        """测试输入成本预估"""
        tracker = TokenTracker()
        
        cost = tracker.estimate_input_cost("claude-sonnet-4-5-20250929", 1000000)
        
        # 1M tokens * $3/1M = $3.00
        self.assertEqual(cost, 3.00)
    
    def test_estimate_input_cost_unknown_model(self):
        """测试未知模型的输入成本预估"""
        tracker = TokenTracker()
        
        cost = tracker.estimate_input_cost("unknown-model", 1000000)
        
        # 回退到 Sonnet
        self.assertEqual(cost, 3.00)


class TestTokenTrackerCostEstimateWithCache(unittest.TestCase):
    """测试 PRD v3 成本预估（考虑缓存）"""
    
    def test_estimate_cost_with_cache_hit(self):
        """测试缓存命中时的成本预估"""
        tracker = TokenTracker()
        
        # 直接测试 estimate_cost_with_cache 方法
        result = tracker.estimate_cost_with_cache(
            model_id="claude-sonnet-4-5-20250929",
            system_tokens=50000,    # 50K 缓存部分
            message_tokens=5000,    # 5K 非缓存部分
            likely_cache_hit=True,
        )
        
        # 缓存部分: 50000 * 3/1M * 0.1 = $0.015
        # 非缓存部分: 5000 * 3/1M = $0.015
        # 总计: $0.03
        expected = 0.015 + 0.015
        self.assertAlmostEqual(result["estimated_input_cost"], expected, places=4)
        self.assertEqual(result["cached_tokens"], 50000)
    
    def test_estimate_cost_with_cache_miss(self):
        """测试缓存未命中时的成本预估"""
        tracker = TokenTracker()
        
        result = tracker.estimate_cost_with_cache(
            model_id="claude-sonnet-4-5-20250929",
            system_tokens=50000,
            message_tokens=5000,
            likely_cache_hit=False,
        )
        
        # 全部按原价: 55000 * 3/1M = $0.165
        expected = 55000 * 3 / 1_000_000
        self.assertAlmostEqual(result["estimated_input_cost"], expected, places=4)
    
    def test_savings_percent_calculation(self):
        """测试节省百分比计算"""
        tracker = TokenTracker()
        
        result = tracker.estimate_cost_with_cache(
            model_id="claude-sonnet-4-5-20250929",
            system_tokens=50000,  # 缓存部分
            message_tokens=5000,   # 非缓存部分
            likely_cache_hit=True,
        )
        
        # 正常价格: 55000 * 3/1M = $0.165
        # 缓存价格: 50000*0.1 + 5000 = $0.015 + $0.015 = $0.03
        # 节省: (0.165 - 0.03) / 0.165 * 100 = ~81.8%
        self.assertGreater(result["savings_percent"], 80)


class TestTokenTrackerFormatting(unittest.TestCase):
    """测试 TokenTracker 格式化功能"""
    
    def test_format_cost_very_small(self):
        """测试极小金额格式化"""
        tracker = TokenTracker()
        
        formatted = tracker.format_cost(0.0005)
        self.assertEqual(formatted, "$0.0005")
    
    def test_format_cost_small(self):
        """测试小金额格式化"""
        tracker = TokenTracker()
        
        formatted = tracker.format_cost(0.05)
        self.assertEqual(formatted, "$0.050")
    
    def test_format_cost_large(self):
        """测试大金额格式化"""
        tracker = TokenTracker()
        
        formatted = tracker.format_cost(1.50)
        self.assertEqual(formatted, "$1.50")
    
    def test_cost_color_green(self):
        """测试绿色（低成本）颜色"""
        tracker = TokenTracker()
        
        color = tracker.cost_color(0.005)
        self.assertEqual(color, "#27AE60")
    
    def test_cost_color_yellow(self):
        """测试黄色（中等成本）颜色"""
        tracker = TokenTracker()
        
        color = tracker.cost_color(0.05)
        self.assertEqual(color, "#F39C12")
    
    def test_cost_color_red(self):
        """测试红色（高成本）颜色"""
        tracker = TokenTracker()
        
        color = tracker.cost_color(0.50)
        self.assertEqual(color, "#E74C3C")


class TestTokenTrackerEstimation(unittest.TestCase):
    """测试 Token 数量预估"""
    
    def test_estimate_tokens_fallback(self):
        """测试回退到字符/4 估算"""
        tracker = TokenTracker()
        
        # tiktoken 不存在时会回退到 len(text) // 4
        text = "a" * 100
        tokens = tracker.estimate_tokens(text)
        
        # 应该回退到 len(text) // 4
        self.assertEqual(tokens, 25)


class TestCostComparison(unittest.TestCase):
    """测试成本对比分析（PRD v3 规格）"""
    
    def test_cache_savings_sonnet_50k(self):
        """测试 Sonnet 50K 文档缓存节省"""
        tracker = TokenTracker()
        
        # 场景：50K 文档缓存
        doc_tokens = 50000
        
        # 正常价格 (无缓存)
        normal_cost = tracker.estimate_input_cost("claude-sonnet-4-5-20250929", doc_tokens)
        
        # 缓存价格 (读取)
        cache_cost = doc_tokens * MODELS["claude-sonnet-4-5-20250929"].input_price / 1_000_000 * CACHE_READ_MULTIPLIER
        
        # 节省百分比
        savings_percent = (normal_cost - cache_cost) / normal_cost * 100
        
        # 应该节省 90%
        self.assertAlmostEqual(savings_percent, 90, places=1)
    
    def test_50_turn_comparison(self):
        """测试 PRD v3 中 50 轮对话的成本对比"""
        tracker = TokenTracker()
        
        # 方案 A: 简单截断
        # 50K 缓存 + 45K 历史
        cost_a = (
            50000 * 3 / 1_000_000 * CACHE_READ_MULTIPLIER +  # 缓存读取
            45000 * 3 / 1_000_000  # 未缓存
        )
        
        # 方案 B: 增量摘要 + 双层缓存
        # 50K 缓存 + 2K 摘要缓存 + 9K 近期
        cost_b = (
            50000 * 3 / 1_000_000 * CACHE_READ_MULTIPLIER +  # 50K 缓存读取
            2000 * 3 / 1_000_000 * CACHE_READ_MULTIPLIER +   # 2K 摘要缓存读取
            9000 * 3 / 1_000_000  # 9K 未缓存
        )
        
        # 方案 B 应该节省超过 60%
        savings = (cost_a - cost_b) / cost_a * 100
        
        self.assertGreater(savings, 60)


if __name__ == "__main__":
    unittest.main()
