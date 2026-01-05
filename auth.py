import requests
import uuid
import time
import random
import hashlib
import json
import base64
import logging
from typing import Optional, Dict
from urllib import parse
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from captcha import Crack
from utils import retry
from constants import (
    AUTH_URL, CAPTCHA_IMAGE_URL, CAPTCHA_CHECK_URL,
    MAX_AUTH_RETRIES, MAX_TOKEN_RETRIES, MAX_CAPTCHA_RETRIES, USER_AGENTS
)

logger = logging.getLogger(__name__)


class AuthManager:
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
        self._get_auth_token()     # 获取Token
        self._process_captcha()    # 处理验证码
        self._generate_cookie()    # 生成Cookie

    def _generate_cookie(self) -> None:
        """生成随机Cookie"""
        self.cookie = f"__jsluid_s={uuid.uuid4().hex[:32]}"

    @retry(max_retries=MAX_TOKEN_RETRIES, initial_delay=2, backoff_factor=1.5)
    def _get_auth_token(self) -> None:
        """获取认证Token"""
        t = str(round(time.time()))
        data = {
            "authKey": hashlib.md5(("testtest" + t).encode()).hexdigest(),
            "timeStamp": t
        }
        
        headers = {
            "User-Agent": USER_AGENTS[0],
            "Referer": "https://beian.miit.gov.cn/",
            "Content-Type": "application/x-www-form-urlencoded",
            "Connection": "keep-alive",
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Origin": "https://beian.miit.gov.cn"
        }
        
        resp = requests.post(
            AUTH_URL,
            headers=headers,
            data=parse.urlencode(data),
            timeout=10
        )
        
        if resp.status_code != 200:
            raise Exception(f"HTTP {resp.status_code} 错误")
            
        json_data = resp.json()
        if "params" not in json_data or "bussiness" not in json_data["params"]:
            raise Exception("响应格式异常")
            
        self.token = json_data["params"]["bussiness"]
        logger.info(f"Token获取成功: {self.token[:10]}...{self.token[-10:]}")

    def aes_ecb_encrypt(self, plaintext: bytes, key: str) -> str:
        """
        使用AES-ECB模式加密明文
        
        Args:
            plaintext: 待加密的字节数据
            key: 加密密钥（字符串）
            
        Returns:
            加密后的Base64编码字符串
        """
        backend = default_backend()
        cipher = Cipher(algorithms.AES(key.encode()), modes.ECB(), backend=backend)
        padding_length = 16 - (len(plaintext) % 16)
        plaintext_padded = plaintext + bytes([padding_length]) * padding_length
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(plaintext_padded) + encryptor.finalize()
        return base64.b64encode(ciphertext).decode('utf-8')

    @retry(max_retries=MAX_AUTH_RETRIES, initial_delay=2, backoff_factor=2)
    def _process_captcha(self) -> None:
        """处理验证码并完成验证（带内层重试机制）"""
        if not self.token:
            raise ValueError("Token未初始化，无法处理验证码")
        
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
                    "Origin": "https://beian.miit.gov.cn"
                }
                
                client_uid = f"point-{uuid.uuid4()}"
                resp = requests.post(
                    CAPTCHA_IMAGE_URL,
                    headers=headers,
                    json={"clientUid": client_uid},
                    timeout=10
                )
                
                if resp.status_code != 200:
                    raise Exception(f"验证码获取失败 HTTP {resp.status_code}")
                    
                params = resp.json()["params"]
                boxes = self.crack.detect(params["bigImage"])
                
                # 修复：先检查是否为None，再检查长度
                if boxes is None:
                    raise Exception("文字检测失败，未检测到任何文字框")
                if len(boxes) != 5:
                    raise Exception(f"文字检测失败，期望5个框，实际检测到{len(boxes)}个框")
                    
                points = self.crack.siamese(params["smallImage"], boxes)
                if len(points) != 4:
                    raise Exception(f"文字匹配失败，期望4个匹配点，实际匹配到{len(points)}个点")
                    
                new_points = [[p[0] + 20, p[1] + 20] for p in points]
                point_json = json.dumps([{"x": p[0], "y": p[1]} for p in new_points])
                enc_point = self.aes_ecb_encrypt(
                    plaintext=point_json.replace(" ", "").encode(),
                    key=params["secretKey"]
                )
                
                check_resp = requests.post(
                    CAPTCHA_CHECK_URL,
                    headers=headers,
                    json={
                        "token": params["uuid"],
                        "secretKey": params["secretKey"],
                        "clientUid": client_uid,
                        "pointJson": enc_point
                    },
                    timeout=10
                )
                
                if check_resp.status_code != 200:
                    raise Exception(f"验证码验证失败 HTTP {check_resp.status_code}")
                    
                check_data = check_resp.json()
                if check_data["code"] != 200:
                    raise Exception(f"验证码验证失败: {check_data.get('msg', '未知错误')}")
                    
                # 成功：保存认证信息并返回
                self.sign = check_data["params"]["sign"]
                self.uuid_token = params["uuid"]
                if captcha_attempt > 1:
                    logger.info(f"验证码验证成功（第{captcha_attempt}次尝试）")
                else:
                    logger.info("验证码验证成功，开始获取ICP备案信息")
                return
                
            except Exception as e:
                error_msg = str(e)
                # 如果是验证码识别失败（检测或匹配失败），尝试重新获取验证码
                if "文字检测失败" in error_msg or "文字匹配失败" in error_msg:
                    if captcha_attempt < MAX_CAPTCHA_RETRIES:
                        logger.warning(f"验证码识别失败（第{captcha_attempt}次尝试）: {error_msg}，正在重新获取验证码...")
                        time.sleep(1)  # 短暂延迟后重试
                        continue
                    else:
                        # 达到最大重试次数，抛出异常让外层重试机制处理
                        logger.error(f"验证码识别连续失败{MAX_CAPTCHA_RETRIES}次: {error_msg}")
                        raise Exception(f"验证码识别失败（已重试{MAX_CAPTCHA_RETRIES}次）: {error_msg}")
                else:
                    # 其他错误（如网络错误、API错误），直接抛出
                    raise

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
                    
        raise RuntimeError("❗ 无法完成认证，请检查：\n1. 网络连接\n2. 验证码识别服务\n3. 目标网站状态")

    @property
    def headers(self) -> Dict[str, str]:
        """获取当前认证头信息"""
        return {
            "Token": self.token or "",
            "Sign": self.sign or "",
            "Uuid": self.uuid_token or "",
            "Cookie": self.cookie or ""
        }