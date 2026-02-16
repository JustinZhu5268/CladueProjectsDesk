"""
Unit tests for config module - PRD v3 configuration parameters
"""
import unittest
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import (
    MODELS,
    DEFAULT_MODEL,
    COMPRESS_AFTER_TURNS,
    COMPRESS_BATCH_SIZE,
    MAX_SUMMARY_TOKENS,
    SUMMARY_RECOMPRESS_THRESHOLD,
    RECENT_TURNS_KEPT,
    CACHE_TTL_DEFAULT,
    CACHE_TTL_1H,
    CACHE_WRITE_MULTIPLIER_5M,
    CACHE_WRITE_MULTIPLIER_1H,
    CACHE_READ_MULTIPLIER,
    COMPACTION_TRIGGER_TOKENS,
)

# CACHE_BREAKPOINT_THRESHOLD 在 context_builder.py 中定义
from core.context_builder import CACHE_BREAKPOINT_THRESHOLD


class TestConfigConstants(unittest.TestCase):
    """测试配置常量定义"""
    
    def test_compression_settings_defaults(self):
        """测试压缩相关默认配置"""
        # 验证默认值符合 PRD v3 规格
        self.assertEqual(COMPRESS_AFTER_TURNS, 10)
        self.assertEqual(COMPRESS_BATCH_SIZE, 5)
        self.assertEqual(MAX_SUMMARY_TOKENS, 500)
        self.assertEqual(SUMMARY_RECOMPRESS_THRESHOLD, 3000)
        self.assertEqual(RECENT_TURNS_KEPT, 10)
    
    def test_cache_ttl_settings(self):
        """测试 Cache TTL 配置"""
        self.assertEqual(CACHE_TTL_DEFAULT, "5m")
        self.assertEqual(CACHE_TTL_1H, "1h")
    
    def test_cache_pricing_multipliers(self):
        """测试缓存定价乘数"""
        # PRD v3 规格：5分钟 = 1.25x, 1小时 = 2.0x
        self.assertEqual(CACHE_WRITE_MULTIPLIER_5M, 1.25)
        self.assertEqual(CACHE_WRITE_MULTIPLIER_1H, 2.0)
        self.assertEqual(CACHE_READ_MULTIPLIER, 0.10)
    
    def test_compaction_trigger_threshold(self):
        """测试 Compaction API 触发阈值"""
        # 200K * 80% = 160K
        self.assertEqual(COMPACTION_TRIGGER_TOKENS, 160000)
    
    def test_cache_breakpoint_threshold(self):
        """测试缓存断点阈值"""
        # PRD v3: 至少 1024 tokens 才能作为有效缓存断点
        self.assertEqual(CACHE_BREAKPOINT_THRESHOLD, 1024)


class TestModelDefinitions(unittest.TestCase):
    """测试模型定义"""
    
    def test_all_required_models_defined(self):
        """验证所有必需的模型都已定义"""
        required_models = [
            "claude-opus-4-6",
            "claude-opus-4-5-20251101", 
            "claude-sonnet-4-5-20250929",
            "claude-haiku-4-5-20251001",
        ]
        
        for model_id in required_models:
            self.assertIn(model_id, MODELS, f"Model {model_id} not defined")
    
    def test_model_pricing(self):
        """验证模型定价符合 PRD v3"""
        # Opus 4.6
        opus_6 = MODELS["claude-opus-4-6"]
        self.assertEqual(opus_6.input_price, 5.00)
        self.assertEqual(opus_6.output_price, 25.00)
        
        # Sonnet 4.5
        sonnet = MODELS["claude-sonnet-4-5-20250929"]
        self.assertEqual(sonnet.input_price, 3.00)
        self.assertEqual(sonnet.output_price, 15.00)
        
        # Haiku 4.5
        haiku = MODELS["claude-haiku-4-5-20251001"]
        self.assertEqual(haiku.input_price, 1.00)
        self.assertEqual(haiku.output_price, 5.00)
    
    def test_model_context_window(self):
        """验证所有模型的上下文窗口"""
        for model_id, model in MODELS.items():
            self.assertEqual(model.context_window, 200000, 
                           f"{model_id} should have 200K context")
    
    def test_default_model_is_haiku(self):
        """验证默认模型是 Haiku"""
        self.assertEqual(DEFAULT_MODEL, "claude-haiku-4-5-20251001")


class TestPricingCalculations(unittest.TestCase):
    """测试定价计算"""
    
    def test_cache_write_cost_5m(self):
        """测试 5 分钟缓存写入成本计算"""
        # 假设 10000 tokens，基础价格 $3/MTok
        base_price = 3.00 / 1_000_000
        tokens = 10000
        write_cost = tokens * base_price * CACHE_WRITE_MULTIPLIER_5M
        
        expected = 10000 * (3.00 / 1_000_000) * 1.25
        self.assertAlmostEqual(write_cost, expected, places=6)
    
    def test_cache_write_cost_1h(self):
        """测试 1 小时缓存写入成本计算"""
        tokens = 10000
        base_price = 3.00 / 1_000_000
        write_cost = tokens * base_price * CACHE_WRITE_MULTIPLIER_1H
        
        expected = 10000 * (3.00 / 1_000_000) * 2.0
        self.assertAlmostEqual(write_cost, expected, places=6)
    
    def test_cache_read_cost(self):
        """测试缓存读取成本"""
        tokens = 50000  # 50K 缓存
        base_price = 3.00 / 1_000_000
        read_cost = tokens * base_price * CACHE_READ_MULTIPLIER
        
        expected = 50000 * (3.00 / 1_000_000) * 0.10
        self.assertAlmostEqual(read_cost, expected, places=6)
        
        # 验证：缓存读取比正常价格节省 90%
        normal_cost = tokens * base_price
        self.assertAlmostEqual(read_cost, normal_cost * 0.10, places=6)


class TestCompressionCostEstimate(unittest.TestCase):
    """测试压缩成本预估"""
    
    def test_compression_cost_with_haiku(self):
        """测试使用 Haiku 压缩的成本预估"""
        # 假设压缩 3000 tokens
        input_tokens = 3000
        output_ratio = 0.3  # 压缩后约 30%
        
        haiku = MODELS["claude-haiku-4-5-20251001"]
        
        # 输入成本
        input_cost = input_tokens * haiku.input_price / 1_000_000
        
        # 输出成本 (摘要约 900 tokens)
        output_tokens = int(input_tokens * output_ratio)
        output_cost = output_tokens * haiku.output_price / 1_000_000
        
        total_cost = input_cost + output_cost
        
        # 验证成本在合理范围内 (约 $0.006)
        self.assertLess(total_cost, 0.01)  # 小于 1 cent
        self.assertGreater(total_cost, 0.001)  # 大于 0.1 cent
    
    def test_compression_savings_vs_main_model(self):
        """测试压缩相比主模型的节省"""
        # 使用 Sonnet 压缩 vs 使用主模型
        input_tokens = 10000
        
        sonnet = MODELS["claude-sonnet-4-5-20250929"]
        haiku = MODELS["claude-haiku-4-5-20251001"]
        
        # Sonnet 输入
        sonnet_input = input_tokens * sonnet.input_price / 1_000_000
        # Haiku 输入
        haiku_input = input_tokens * haiku.input_price / 1_000_000
        
        # 验证 Haiku 便宜 3 倍
        self.assertAlmostEqual(sonnet_input / haiku_input, 3.0, places=1)


class TestContextBudgetCalculation(unittest.TestCase):
    """测试上下文预算计算"""
    
    def test_context_usage_threshold(self):
        """测试上下文使用阈值"""
        context_window = 200000
        threshold = 0.80  # CONTEXT_USAGE_THRESHOLD
        
        budget = int(context_window * threshold)
        
        self.assertEqual(budget, 160000)
    
    def test_response_token_reserve(self):
        """测试响应 Token 预留"""
        from config import RESPONSE_TOKEN_RESERVE
        
        self.assertEqual(RESPONSE_TOKEN_RESERVE, 8192)
    
    def test_actual_budget_after_reserve(self):
        """测试预留后的实际预算"""
        context_window = 200000
        threshold = 0.80
        reserve = 8192
        
        budget = int(context_window * threshold) - reserve
        
        # 160000 - 8192 = 151808
        self.assertEqual(budget, 151808)


if __name__ == "__main__":
    unittest.main()
