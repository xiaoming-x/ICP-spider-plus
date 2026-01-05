import pandas as pd
import random
import time
import os
import logging
from typing import Dict, List, Any, Optional
from curl_cffi import requests as cffi_requests
from constants import DETAIL_QUERY_URL, TYPE_MAPPING, PROXY_TEST_URL, DEFAULT_TIMEOUT

logger = logging.getLogger(__name__)


def retry(max_retries: int, initial_delay: float = 2, backoff_factor: float = 2):
    """通用重试装饰器"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            last_exception = None
            for retry in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    delay = initial_delay * (backoff_factor ** retry)
                    logger.warning(
                        f"{func.__name__}失败（第{retry+1}次重试）: {str(e)}，"
                        f"{delay:.1f}秒后重试..."
                    )
                    time.sleep(delay)
            raise last_exception  # 达到最大重试次数抛出最后一次异常
        return wrapper
    return decorator


def get_current_time_filename() -> str:
    """生成带当前时间戳的文件名"""
    return f"results_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"


def generate_modern_headers(auth_headers: Dict[str, str]) -> Dict[str, str]:
    """生成现代浏览器请求头"""
    browser_version = random.choice(["124", "123", "122"])
    platform = random.choice(["Windows", "macOS"])
    base_headers = {
        "Host": "hlwicpfwc.miit.gov.cn",
        "Sec-Ch-Ua": f"\"Chromium\";v=\"{browser_version}\", \"Google Chrome\";v=\"{browser_version}\", \"Not-A.Brand\";v=\"99\"",
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": f"\"{platform}\"",
        "User-Agent": f"Mozilla/5.0 ({'Windows NT 10.0; Win64; x64' if 'Windows' in platform else 'Macintosh; Intel Mac OS X 10_15_7'}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{browser_version}.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Referer": "https://beian.miit.gov.cn/",
        "Origin": "https://beian.miit.gov.cn"
    }
    return {** base_headers, **auth_headers}


def process_response(response_data: Dict[str, Any], service_type: int, headers: Dict[str, str]) -> List[Dict[str, Any]]:
    """处理API响应数据，提取备案信息"""
    results = []
    if response_data.get("success"):
        for item in response_data["params"]["list"]:
            # 基础信息提取
            result = {
                "unitName": item.get("unitName"),
                "mainLicence": item.get("mainLicence"),  # 临时值，后续可能更新
                "serviceLicence": item.get("serviceLicence"),
                "updateRecordTime": item.get("updateRecordTime")
            }

            # 处理APP、小程序和快应用类型：调用详情接口补充信息
            if service_type in [6, 7, 8]:  # 6=app, 7=miniapp, 8=quickapp
                data_id = item.get("dataId")
                if data_id:
                    try:
                        # 调用详情接口
                        detail_resp = cffi_requests.post(
                            DETAIL_QUERY_URL,
                            headers=headers,
                            json={"dataId": data_id, "serviceType": service_type},
                            impersonate="chrome110",
                            timeout=DEFAULT_TIMEOUT
                        )
                        
                        if detail_resp.status_code == 200:
                            detail_data = detail_resp.json()
                            if detail_data.get("success") and "params" in detail_data:
                                detail = detail_data["params"]
                                # 更新详情字段
                                result["mainLicence"] = detail.get("mainLicence", result["mainLicence"])
                                result["serviceName"] = detail.get("serviceName", "")  # 从详情接口获取
                            else:
                                logger.warning(f"详情查询失败 (dataId={data_id}): {detail_data.get('msg', '未知错误')}")
                        else:
                            logger.warning(f"详情接口HTTP错误 (dataId={data_id}): 状态码{detail_resp.status_code}")
                    except Exception as e:
                        logger.error(f"详情查询异常 (dataId={data_id}): {str(e)}")
                else:
                    logger.warning("缺少dataId，无法查询详情")

            # 处理Web类型：保留原有逻辑
            else:
                result["domain"] = item.get("domain")

            results.append(result)
    return results


def write_to_excel(results_dict: Dict[str, List[Dict]], output_file: Optional[str] = None) -> None:
    """将查询结果写入Excel文件"""
    output_file = output_file or get_current_time_filename()
    has_data = any(bool(data) for data in results_dict.values())
    
    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        if not has_data:
            pd.DataFrame([["无备案数据"]], columns=["提示"]).to_excel(writer, sheet_name="默认", index=False)
        else:
            for sheet_name, data in results_dict.items():
                if data:
                    df = pd.DataFrame(data)
                    # Excel工作表名称最大31字符
                    safe_name = sheet_name[:31]
                    df.to_excel(writer, sheet_name=safe_name, index=False)
    
    logger.info(f"结果已保存至：{output_file}")


def load_proxies() -> List[str]:
    """从proxy.txt加载代理列表"""
    try:
        with open('proxy.txt', 'r') as f:
            proxies = [line.strip() for line in f if line.strip()]
            logger.info(f"已加载 {len(proxies)} 个代理")
            return proxies
    except FileNotFoundError:
        logger.warning("未找到proxy.txt文件，不使用代理")
        return []


def validate_proxies(proxies: List[str]) -> List[str]:
    """验证代理格式（移除了连通性测试）"""
    valid_proxies = []
    for p in proxies:
        # 仅验证格式，不测试连通性
        if p.startswith(("http://", "https://", "socks5://")):
            valid_proxies.append(p)
            logger.info(f"代理格式有效：{p}")
        else:
            logger.warning(f"忽略无效代理格式：{p}")
    return valid_proxies


def format_proxy(proxy_str: str) -> Dict[str, str]:
    """格式化代理地址"""
    if proxy_str.startswith(("socks5://", "http://", "https://")):
        return {"http": proxy_str, "https": proxy_str}
    return {"http": f"http://{proxy_str}", "https": f"https://{proxy_str}"}
