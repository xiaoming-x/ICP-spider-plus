"""
认证管理模块 — 处理工信部 ICP 备案查询接口的认证与滑块验证码

从 icp-query-tool 的滑块验证码方案移植，替代原有的 YOLO+Siamese 点选方案。
"""

import base64
import hashlib
import logging
import random
import time
import uuid
from typing import Any, Dict, Optional

import requests
import urllib3
from urllib3.exceptions import InsecureRequestWarning

from captcha import Crack
from constants import (
    AUTH_URL,
    CAPTCHA_IMAGE_URL,
    CAPTCHA_CHECK_URL,
    MAX_AUTH_RETRIES,
    MAX_TOKEN_RETRIES,
    MAX_CAPTCHA_RETRIES,
    USER_AGENTS,
    DEFAULT_TIMEOUT,
)

# 全局关闭未验证 HTTPS 请求的告警
urllib3.disable_warnings(InsecureRequestWarning)

logger = logging.getLogger(__name__)


class AuthManager:
    """认证管理器 — 处理工信部 ICP 接口的登录认证与滑块验证码"""

    BASE_URL = "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/"

    def __init__(self):
        self.crack = Crack()
        self.token: Optional[str] = None
        self.sign: Optional[str] = None
        self.uuid_token: Optional[str] = None
        self.cookie: Optional[str] = None
        self._reset_auth()  # 初始化认证信息

    def _reset_auth(self) -> None:
        """重置所有认证信息并重新初始化"""
        self.token = None
        self.sign = None
        self.uuid_token = None
        self.cookie = None
        self._get_auth_token()     # 获取 Token
        self._process_captcha()    # 处理滑块验证码
        self._generate_cookie()    # 生成 Cookie

    def _generate_cookie(self) -> None:
        """生成随机 Cookie"""
        self.cookie = f"__jsluid_s={uuid.uuid4().hex[:32]}"

    @staticmethod
    def _auth_key(account: str, secret: str, ts_ms: int) -> str:
        return hashlib.md5(
            f"{account}{secret}{ts_ms}".encode("utf-8")
        ).hexdigest()

    def _get_auth_token(self) -> None:
        """获取认证 Token（与 icp-query-tool 一致，使用 requests）"""
        ts_ms = int(time.time() * 1000)
        payload = {
            "authKey": self._auth_key("test", "test", ts_ms),
            "timeStamp": ts_ms,
        }

        # 同 icp-query-tool 的 auth 方法：使用 urlencoded 格式
        resp = requests.post(
            AUTH_URL,
            data=payload,
            headers={
                "User-Agent": USER_AGENTS[0],
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://beian.miit.gov.cn",
                "Referer": "https://beian.miit.gov.cn/",
                "Accept": "application/json, text/plain, */*",
            },
            timeout=DEFAULT_TIMEOUT,
            verify=False,
        )
        if resp.status_code == 403:
            raise RuntimeError(
                "HTTP 403 Forbidden: auth 被风控拦截，请稍后重试或更换网络出口"
            )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 200:
            raise RuntimeError(f"auth failed: {data}")
        params = data.get("params") or {}
        req_token = params.get("token") or params.get("bussiness")
        if not req_token:
            raise RuntimeError(f"auth response missing token: {data}")
        self.token = req_token
        logger.info(
            f"Token 获取成功: {self.token[:10]}...{self.token[-10:]}"
        )

    def _process_captcha(self) -> None:
        """处理滑块验证码（从 icp-query-tool 移植，带重试机制）"""
        if not self.token:
            raise ValueError("Token 未初始化，无法处理验证码")

        # 内层重试：验证码识别失败时自动重新获取验证码
        for captcha_attempt in range(1, MAX_CAPTCHA_RETRIES + 1):
            try:
                headers = {
                    "User-Agent": USER_AGENTS[0],
                    "Referer": "https://beian.miit.gov.cn/",
                    "Token": self.token,
                    "Connection": "keep-alive",
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Origin": "https://beian.miit.gov.cn",
                }

                client_uid = f"point-{uuid.uuid4()}"
                resp = requests.post(
                    CAPTCHA_IMAGE_URL,
                    headers=headers,
                    json={"clientUid": client_uid},
                    timeout=DEFAULT_TIMEOUT,
                    verify=False,
                )
                if resp.status_code != 200:
                    raise Exception(
                        f"验证码获取失败 HTTP {resp.status_code}"
                    )

                data = resp.json()
                params = data.get("params") or {}
                big_b64 = params.get("bigImage")
                small_b64 = params.get("smallImage")
                if not big_b64 or not small_b64:
                    raise Exception(
                        f"验证码图片数据缺失: {list(params.keys())}"
                    )

                big_img = base64.b64decode(big_b64)
                small_img = base64.b64decode(small_b64)
                offset = self.crack.calc_offset(big_img, small_img)
                self.uuid_token = params.get("uuid", "")

                logger.debug(f"滑块偏移量: {offset}")

                # 提交验证
                check_resp = requests.post(
                    CAPTCHA_CHECK_URL,
                    headers=headers,
                    json={
                        "key": self.uuid_token,
                        "value": str(offset),
                    },
                    timeout=DEFAULT_TIMEOUT,
                    verify=False,
                )
                if check_resp.status_code != 200:
                    raise Exception(
                        f"验证码验证失败 HTTP {check_resp.status_code}"
                    )

                check_data = check_resp.json()
                if not check_data.get("success"):
                    raise Exception(
                        f"验证码验证失败: {check_data.get('msg', '未知错误')}"
                    )

                # 成功：保存 sign
                check_params = check_data.get("params")
                if isinstance(check_params, dict):
                    self.sign = check_params.get("sign", "")
                else:
                    self.sign = check_params or ""
                if not self.sign:
                    raise Exception(
                        f"验证码验证成功但 sign 缺失: {check_data}"
                    )

                if captcha_attempt > 1:
                    logger.info(
                        f"滑块验证码验证成功（第{captcha_attempt}次尝试）"
                    )
                else:
                    logger.info("滑块验证码验证成功，开始查询 ICP 备案信息")
                return

            except Exception as e:
                error_msg = str(e)
                if captcha_attempt < MAX_CAPTCHA_RETRIES:
                    logger.warning(
                        f"滑块验证码识别失败（第{captcha_attempt}次尝试）: "
                        f"{error_msg}，正在重新获取验证码..."
                    )
                    time.sleep(1)
                    continue
                else:
                    logger.error(
                        f"滑块验证码连续失败{MAX_CAPTCHA_RETRIES}次: "
                        f"{error_msg}"
                    )
                    raise Exception(
                        f"滑块验证码识别失败（已重试{MAX_CAPTCHA_RETRIES}次）: "
                        f"{error_msg}"
                    )

    def update_headers(self) -> None:
        """更新认证信息（带重试机制）"""
        max_retries = 10
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"\n▶ 认证尝试 {attempt}/{max_retries}")
                self._reset_auth()
                logger.info("✅ 认证成功")
                return
            except Exception as e:
                logger.error(f"❌ 失败原因: {str(e)}")
                if attempt < max_retries:
                    delay = random.randint(5, 10)
                    logger.info(f"⏳ {delay}秒后重试...")
                    time.sleep(delay)

        raise RuntimeError(
            "❗ 无法完成认证，请检查：\n1. 网络连接\n2. 验证码识别服务\n3. 目标网站状态"
        )

    @property
    def headers(self) -> Dict[str, str]:
        """获取当前认证头信息"""
        return {
            "Token": self.token or "",
            "Sign": self.sign or "",
            "Uuid": self.uuid_token or "",
            "Cookie": self.cookie or "",
        }

    # ── 以下是向后兼容的辅助方法（供外部直接使用，类似 icp-query-tool 的 MiitIcpAutoClient） ──

    def get_check_images(self, client_uid: str | None = None) -> dict[str, Any]:
        """获取验证码图片（兼容 icp-query-tool 接口）"""
        if not self.token:
            self._get_auth_token()
        if not client_uid:
            client_uid = str(uuid.uuid4())
        resp = requests.post(
            CAPTCHA_IMAGE_URL,
            json={"clientUid": client_uid},
            headers={
                "User-Agent": USER_AGENTS[0],
                "Referer": "https://beian.miit.gov.cn/",
                "Token": self.token,
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://beian.miit.gov.cn",
            },
            timeout=DEFAULT_TIMEOUT,
            verify=False,
        )
        resp.raise_for_status()
        data = resp.json()
        params = data.get("params") or {}
        self.uuid_token = params.get("uuid", "")
        if not self.uuid_token:
            raise RuntimeError(f"getCheckImagePoint failed: {data}")
        return data

    def verify_slider(self, image_payload: dict[str, Any]) -> tuple[int, str]:
        """验证滑块（兼容 icp-query-tool 接口）"""
        params = image_payload.get("params") or {}
        big_b64 = params.get("bigImage")
        small_b64 = params.get("smallImage")
        if not big_b64 or not small_b64:
            raise RuntimeError(f"captcha image missing: {image_payload}")

        big_img_bytes = base64.b64decode(big_b64)
        small_img_bytes = base64.b64decode(small_b64)
        offset = self.crack.calc_offset(big_img_bytes, small_img_bytes)

        resp = requests.post(
            CAPTCHA_CHECK_URL,
            json={"key": self.uuid_token, "value": str(offset)},
            headers={"Token": self.token},
            timeout=DEFAULT_TIMEOUT,
            verify=False,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            raise RuntimeError(
                f"checkImage failed, offset={offset}, resp={data}"
            )

        params2 = data.get("params")
        if isinstance(params2, dict):
            self.sign = params2.get("sign", "")
        else:
            self.sign = params2 or ""
        if not self.sign:
            raise RuntimeError(
                f"checkImage success but sign missing: {data}"
            )
        return offset, self.sign
