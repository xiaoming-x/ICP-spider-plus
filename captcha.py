"""
验证码识别模块 — 基于 ddddocr + OpenCV 的滑块验证码识别

替代原有的 YOLO + Siamese 点选验证码方案。
从 icp-query-tool 的 miit_icp_auto_query.py 移植并适配。
"""

import base64
from io import BytesIO
from typing import Any

import cv2
import ddddocr
import numpy as np
from PIL import Image


class Crack:
    """滑块验证码识别器（使用 ddddocr + OpenCV 掩码模板匹配）"""

    def __init__(self):
        self._slide = ddddocr.DdddOcr(det=False, ocr=False, show_ad=False)
        self.big_img: np.ndarray | None = None

    @staticmethod
    def read_base64_image(base64_string: str) -> np.ndarray:
        """将 Base64 字符串解码为 OpenCV 图像（BGR 格式）"""
        img_data = base64.b64decode(base64_string)
        np_array = np.frombuffer(img_data, np.uint8)
        return cv2.imdecode(np_array, cv2.IMREAD_COLOR)

    def calc_offset(self, big_img: bytes, small_img: bytes) -> int:
        """
        计算滑块偏移量

        使用 ddddocr + OpenCV 掩码模板匹配 + 透明边裁剪补偿，
        从多个候选值中选取最可靠的一个。

        Args:
            big_img: 背景图（大图）原始字节
            small_img: 滑块图（小图）原始字节

        Returns:
            滑块偏移量（像素）
        """
        candidates: list[int] = []

        # 1) ddddocr 候选
        for simple_target in (False, True):
            try:
                result = self._slide.slide_match(
                    target_bytes=small_img,
                    background_bytes=big_img,
                    simple_target=simple_target,
                )
                target = result.get("target")
                if isinstance(target, list) and len(target) >= 1:
                    x = int(target[0])
                    if 1 <= x <= 435:
                        candidates.append(x)
            except Exception:
                pass

        # 2) OpenCV 掩码模板匹配（一次命中率更高）
        cv_x: int | None = None
        try:
            big_gray = cv2.imdecode(
                np.frombuffer(big_img, dtype=np.uint8), cv2.IMREAD_GRAYSCALE
            )
            small_rgba = cv2.imdecode(
                np.frombuffer(small_img, dtype=np.uint8), cv2.IMREAD_UNCHANGED
            )
            if (
                big_gray is not None
                and small_rgba is not None
                and len(small_rgba.shape) == 3
                and small_rgba.shape[2] == 4
            ):
                small_gray = cv2.cvtColor(small_rgba[:, :, :3], cv2.COLOR_BGR2GRAY)
                alpha_mask = small_rgba[:, :, 3]
                res = cv2.matchTemplate(
                    big_gray, small_gray, cv2.TM_CCORR_NORMED, mask=alpha_mask
                )
                _, _, _, max_loc = cv2.minMaxLoc(res)
                cv_x = int(max_loc[0])
                if 1 <= cv_x <= 435:
                    candidates.append(cv_x)
        except Exception:
            pass

        # 3) 透明边裁剪后再次 ddddocr，作为补偿候选
        try:
            rgba = Image.open(BytesIO(small_img)).convert("RGBA")
            alpha = np.array(rgba)[:, :, 3]
            ys, xs = np.where(alpha > 8)
            if len(xs) > 0 and len(ys) > 0:
                left, top, right, bottom = (
                    xs.min(),
                    ys.min(),
                    xs.max(),
                    ys.max(),
                )
                cropped = rgba.crop((left, top, right + 1, bottom + 1))
                buf = BytesIO()
                cropped.save(buf, format="PNG")
                result = self._slide.slide_match(
                    target_bytes=buf.getvalue(),
                    background_bytes=big_img,
                    simple_target=True,
                )
                target = result.get("target")
                if isinstance(target, list) and len(target) >= 1:
                    x = int(target[0])
                    if 1 <= x <= 435:
                        candidates.append(x)
        except Exception:
            pass

        if not candidates:
            raise RuntimeError("failed to compute slider offset by ddddocr/opencv")

        # 去重后按与 cv_x 的接近程度排序；若无 cv_x，则优先较大的候选（经验上更稳定）
        uniq = sorted(set(candidates))
        if cv_x is not None:
            uniq.sort(key=lambda v: abs(v - cv_x))
            return uniq[0]
        return sorted(uniq, reverse=True)[0]

    def detect(self, big_img_b64: str) -> list[list[int]]:
        """
        （兼容旧接口）接收 base64 大图，返回滑块偏移占位结果

        注意：此方法与旧版 YOLO 检测签名兼容，但实际返回的是偏移量伪框。
        新代码请直接使用 calc_offset。
        """
        # 仅保存大图供外部参考
        self.big_img = self.read_base64_image(big_img_b64)
        # 返回一个伪框占位
        return [[0, 0, 100, 100]]

    def siamese(self, small_img: str, boxes: list[list[int]]) -> list[tuple[int, int]]:
        """
        （兼容旧接口）旧版 Siamese 匹配的占位方法

        这个方法不应该被新 auth 流程调用，保留仅为避免 import 断裂。
        """
        raise RuntimeError(
            "siamese() is not available in slider-based captcha mode. "
            "Use calc_offset() directly."
        )
