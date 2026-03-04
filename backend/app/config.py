import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/realestate.db")
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
REFRESH_HOUR = int(os.getenv("REFRESH_HOUR", "8"))
REFRESH_MINUTE = int(os.getenv("REFRESH_MINUTE", "0"))

# 腾讯云 API 密钥（保留兼容，非必需）
TENCENT_SECRET_ID = os.getenv("HUNYUAN_SECRET_ID", "")
TENCENT_SECRET_KEY = os.getenv("HUNYUAN_SECRET_KEY", "")

# LKEAP OpenAI 兼容接口 API Key（三模型共用）
LKEAP_API_KEY = os.getenv("LKEAP_API_KEY", "")

# ── DeepSeek V3.2 配置（LKEAP OpenAI 兼容接口）──
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v3.2")
DEEPSEEK_ENABLED = os.getenv("DEEPSEEK_ENABLED", "true").lower() == "true"

# ── GLM-5 配置（LKEAP OpenAI 兼容接口）──
GLM_MODEL = os.getenv("GLM_MODEL", "glm-5")
GLM_ENABLED = os.getenv("GLM_ENABLED", "true").lower() == "true"

# ── Kimi K2.5 配置（LKEAP OpenAI 兼容接口）──
KIMI_MODEL = os.getenv("KIMI_MODEL", "kimi-k2.5")
KIMI_ENABLED = os.getenv("KIMI_ENABLED", "true").lower() == "true"

# 三模型融合权重（之和应为1.0）
DEEPSEEK_WEIGHT = float(os.getenv("DEEPSEEK_WEIGHT", "0.4"))
GLM_WEIGHT = float(os.getenv("GLM_WEIGHT", "0.3"))
KIMI_WEIGHT = float(os.getenv("KIMI_WEIGHT", "0.3"))

# JWT 配置
JWT_SECRET = os.getenv("JWT_SECRET", "real-estate-stock-agent-secret-key-2025")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 72

# 默认管理员（首次启动自动创建）
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
