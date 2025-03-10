import requests
import uuid
import time
import hashlib
import json
import base64
from urllib import parse
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from captcha import Crack


class AuthManager:
    def __init__(self):
        self.crack = Crack()
        self._reset_auth()  # 初始化认证信息

    def _reset_auth(self):
        """重置所有认证信息"""
        self.token = None
        self.sign = None
        self.uuid_token = None
        self.cookie = None
        self._get_auth_token()     # 获取Token
        self._process_captcha()    # 处理验证码
        self._generate_cookie()    # 生成Cookie

    def _generate_cookie(self):
        self.cookie = f"__jsluid_s={uuid.uuid4().hex[:32]}"

    def _get_auth_token(self):
        for retry in range(3):
            try:
                t = str(round(time.time()))
                data = {
                    "authKey": hashlib.md5(("testtest" + t).encode()).hexdigest(),
                    "timeStamp": t
                }
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                    "Referer": "https://beian.miit.gov.cn/",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Connection": "keep-alive",
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "Origin": "https://beian.miit.gov.cn"
                }
                resp = requests.post(
                    "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/auth",
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
                print("Token获取成功:", self.token[:10]+"..."+self.token[-10:])
                return
            except Exception as e:
                print(f"获取Token失败（第{retry+1}次重试）: {str(e)}")
                if retry == 2:
                    raise RuntimeError("无法获取Token，请检查网络或参数")
                time.sleep(2 if retry == 0 else 5)

    def aes_ecb_encrypt(self, plaintext, key):
        backend = default_backend()
        cipher = Cipher(algorithms.AES(key.encode()), modes.ECB(), backend=backend)
        padding_length = 16 - (len(plaintext) % 16)
        plaintext_padded = plaintext + bytes([padding_length]) * padding_length
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(plaintext_padded) + encryptor.finalize()
        return base64.b64encode(ciphertext).decode('utf-8')

    def _process_captcha(self):
        for retry in range(3):
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
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
                    "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/image/getCheckImagePoint",
                    headers=headers,
                    json={"clientUid": client_uid},
                    timeout=10
                )
                if resp.status_code != 200:
                    raise Exception(f"验证码获取失败 HTTP {resp.status_code}")
                params = resp.json()["params"]
                boxes = self.crack.detect(params["bigImage"])
                if not boxes or len(boxes) != 5:
                    raise Exception("文字检测失败，获取到{}个框".format(len(boxes)))
                points = self.crack.siamese(params["smallImage"], boxes)
                if len(points) != 4:
                    raise Exception("文字匹配失败，匹配到{}个点".format(len(points)))
                new_points = [[p[0] + 20, p[1] + 20] for p in points]
                point_json = json.dumps([{"x": p[0], "y": p[1]} for p in new_points])
                enc_point = self.aes_ecb_encrypt(
                    plaintext=point_json.replace(" ", "").encode(),
                    key=params["secretKey"]
                )
                check_resp = requests.post(
                    "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/image/checkImage",
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
                self.sign = check_data["params"]["sign"]
                self.uuid_token = params["uuid"]
                print("验证码验证成功，开始获取ICP备案信息")
                return
            except Exception as e:
                print(f"验证码处理失败（第{retry+1}次重试）: {str(e)}")
                if retry == 2:
                    raise RuntimeError("验证码处理失败")
                time.sleep(2 if retry == 0 else 5)
                self._get_auth_token()

    def update_headers(self):
        """更新所有认证信息"""
        try:
            print("\n正在更新认证信息...")
            self._reset_auth()  # 重新初始化认证信息
            print("认证信息更新成功")
        except Exception as e:
            print(f"认证信息更新失败: {str(e)}")
            raise

    @property
    def headers(self):
        return {
            "Token": self.token,
            "Sign": self.sign,
            "Uuid": self.uuid_token,
            "Cookie": self.cookie
        }