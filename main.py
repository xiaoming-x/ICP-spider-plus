import argparse
import time
import random
import sys
import logging
from typing import List, Optional, Dict, Any
from curl_cffi import requests as cffi_requests
from auth import AuthManager
from utils import (
    generate_modern_headers, process_response, write_to_excel,
    load_proxies, validate_proxies, format_proxy, retry
)
from constants import QUERY_URL, TYPE_MAPPING, DEFAULT_TIMEOUT

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description='ICP备案查询工具')
    parser.add_argument('unit_name', nargs='?', help='查询单位名称')
    parser.add_argument('-f', '--file', help='批量查询文件')
    parser.add_argument('-o', '--output', help='输出文件名')
    parser.add_argument('-t', '--type', choices=['web', 'app', 'miniapp', 'quickapp', 'all'], default='web', help='查询类型:网站、APP、小程序、快应用、全部')
    parser.add_argument('-p', '--proxy_rotate', type=int, help='代理轮换间隔（每个代理处理N个请求后切换）')
    args = parser.parse_args()

    auth_manager = AuthManager()
    raw_proxies = load_proxies()
    available_proxies = validate_proxies(raw_proxies)
    use_proxy = len(available_proxies) > 0
    proxy_index = 0  # 代理索引，用于轮询
    requests_per_proxy = 0  # 当前代理已处理的请求数
    
    query_types = ["web", "app", "miniapp", "quickapp"] if args.type == "all" else [args.type]
    units = load_units(args)
    
    all_results: Dict[str, List[Dict[str, Any]]] = {t: [] for t in query_types}
    blocked = False

    try:
        for unit_idx, unit in enumerate(units):
            logger.info(f"\n查询进度：{unit_idx+1}/{len(units)} - {unit}")
            
            # 确定当前使用的代理
            current_proxy: Optional[str] = None
            if use_proxy and available_proxies:
                # 检查是否需要轮换代理
                if args.proxy_rotate and requests_per_proxy >= args.proxy_rotate:
                    proxy_index = (proxy_index + 1) % len(available_proxies)
                    requests_per_proxy = 0  # 重置计数
                    logger.info(f"达到轮换间隔，切换到代理 #{proxy_index + 1}")
                
                current_proxy = available_proxies[proxy_index]
                logger.info(f"当前使用代理：{current_proxy} (已处理 {requests_per_proxy}/{args.proxy_rotate or '无限'} 个请求)")

            for query_type in query_types:
                if blocked:
                    break
                
                service_type = TYPE_MAPPING[query_type]
                logger.info(f"正在查询 {query_type} 类型...")
                success = False

                while not success:
                    headers = generate_modern_headers(auth_manager.headers)

                    try:
                        # 发送请求
                        response = cffi_requests.post(
                            QUERY_URL,
                            headers=headers,
                            json={"pageNum": "1", "pageSize": "100", "unitName": unit, "serviceType": service_type},
                            impersonate="chrome110",
                            proxies=format_proxy(current_proxy) if current_proxy else None,
                            timeout=DEFAULT_TIMEOUT
                        )
                        
                        # 增加当前代理的请求计数
                        if current_proxy:
                            requests_per_proxy += 1

                        # 403 处理逻辑
                        if response.status_code == 403:
                            logger.warning(f"代理 {current_proxy} 返回403，尝试切换代理...")
                            if available_proxies and len(available_proxies) > 1:
                                # 立即切换到下一个代理
                                proxy_index = (proxy_index + 1) % len(available_proxies)
                                current_proxy = available_proxies[proxy_index]
                                requests_per_proxy = 0  # 重置计数
                                logger.info(f"已切换到新代理：{current_proxy}")
                                continue
                            else:
                                logger.error("无其他代理可用，退出程序")
                                sys.exit(1)

                        # 处理响应数据
                        if response.status_code == 200:
                            response_data = response.json()
                            if response_data.get("code") == 401:
                                auth_manager.update_headers()
                                logger.info("Token已更新，正在重试...")
                                continue
                            
                            if response_data.get("success"):
                                all_results[query_type].extend(
                                    process_response(response_data, service_type, headers)
                                )
                                success = True
                                # 智能延时
                                delay = random.uniform(3, 4) if not current_proxy else random.uniform(2, 3)
                                time.sleep(delay)
                                logger.info(f"请求成功，随机延迟: {delay:.2f}秒")
                            else:
                                raise Exception(f"API返回错误：{response_data.get('msg')}")
                        else:
                            raise Exception(f"HTTP错误代码：{response.status_code}")

                    except Exception as e:
                        logger.error(f"请求失败：{str(e)}")
                        if current_proxy and available_proxies:
                            # 切换到下一个代理
                            proxy_index = (proxy_index + 1) % len(available_proxies)
                            current_proxy = available_proxies[proxy_index]
                            requests_per_proxy = 0  # 重置计数
                            logger.info(f"切换到新代理：{current_proxy}")
                            continue
                        else:
                            logger.error("无可用代理，退出程序")
                            sys.exit(1)

                if not success:
                    logger.warning(f"{query_type} 类型查询失败")
                    
    except KeyboardInterrupt:
        logger.info("\n操作中断，正在保存数据...")
    finally:
        write_to_excel(all_results, args.output)


def load_units(args) -> List[str]:
    """加载查询单位列表"""
    if args.file:
        try:
            with open(args.file, 'r', encoding='utf-8') as f:
                units = [line.strip() for line in f if line.strip()]
                logger.info(f"从文件加载 {len(units)} 个查询单位")
                return units
        except Exception as e:
            logger.error(f"加载文件失败: {str(e)}")
            sys.exit(1)
    elif args.unit_name:
        return [args.unit_name]
    else:
        logger.error("请指定查询单位名称或批量查询文件")
        sys.exit(1)


if __name__ == '__main__':
    main()
