"""常量配置文件，集中管理所有硬编码参数"""

# API地址
AUTH_URL = "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/auth"
CAPTCHA_IMAGE_URL = "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/image/getCheckImagePoint"
CAPTCHA_CHECK_URL = "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/image/checkImage"
QUERY_URL = "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/icpAbbreviateInfo/queryByCondition"
DETAIL_QUERY_URL = "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/icpAbbreviateInfo/queryDetailByAppAndMiniId"

# 服务类型映射
TYPE_MAPPING = {"web": 1, "app": 6, "miniapp": 7, "quickapp": 8}

# 模型路径
YOLO_MODEL_PATH = "./onnx/yolov8.onnx"
SIAMESE_MODEL_PATH = "./onnx/siamese.onnx"

# 重试配置
MAX_AUTH_RETRIES = 3
MAX_REQUEST_RETRIES = 3
MAX_TOKEN_RETRIES = 10
MAX_CAPTCHA_RETRIES = 5  # 验证码识别失败时的最大重试次数（每次重新获取验证码）
MAX_DETAIL_QUERY_RETRIES = 3  # 详情查询失败时的最大重试次数
MAX_MAIN_QUERY_RETRIES = 3  # 主查询失败时的最大重试次数（未使用代理时）

# 请求配置
DEFAULT_TIMEOUT = 10
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
]

# 代理测试地址
PROXY_TEST_URL = "http://icanhazip.com"