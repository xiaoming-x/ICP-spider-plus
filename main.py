import argparse
import time
import random
import sys
from curl_cffi import requests as cffi_requests
from auth import AuthManager
from utils import *


def main():
    parser = argparse.ArgumentParser(description='ICP备案查询工具')
    parser.add_argument('unit_name', nargs='?', help='查询单位名称')
    parser.add_argument('-f', '--file', help='批量查询文件')
    parser.add_argument('-o', '--output', help='输出文件名')
    parser.add_argument('-t', '--type', choices=['web', 'app', 'miniapp', 'all'], default='web', help='查询类型')
    parser.add_argument('-p', '--proxy_rotate', type=int, help='代理轮换间隔')
    args = parser.parse_args()

    auth_manager = AuthManager()
    raw_proxies = load_proxies()
    available_proxies = validate_proxies(raw_proxies)  # 新增代理验证函数
    use_proxy = len(available_proxies) > 0

    proxy_index = request_count = 0
    last_proxy_used = None
    query_types = ["web", "app", "miniapp"] if args.type == "all" else [args.type]
    units = load_units(args)
    
    all_results = {t: [] for t in query_types}
    blocked = False

    try:
        for unit_idx, unit in enumerate(units):
            print(f"\n查询进度：{unit_idx+1}/{len(units)} - {unit}")
            
            # 代理切换逻辑（仅在启用代理轮换时执行）
            if use_proxy and available_proxies and args.proxy_rotate:
                if request_count % args.proxy_rotate == 0:
                    proxy_index = (proxy_index + 1) % len(available_proxies)
                current_proxy = available_proxies[proxy_index]
                
                # 打印代理信息（如果代理发生变化）
                if current_proxy != last_proxy_used:
                    print(f"使用代理：{current_proxy}")
                    last_proxy_used = current_proxy
            else:
                current_proxy = None  # 未启用代理轮换时，不使用代理

            for query_type in query_types:
                if blocked:
                    break
                
                service_type = TYPE_MAPPING[query_type]
                print(f"正在查询 {query_type} 类型...")
                success = False

                while not success:
                    headers = generate_modern_headers(auth_manager.headers)

                    try:
                        # 发送请求
                        response = cffi_requests.post(
                            "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/icpAbbreviateInfo/queryByCondition",
                            headers=headers,
                            json={"pageNum": "", "pageSize": "", "unitName": unit, "serviceType": service_type},
                            impersonate="chrome110",
                            proxies=format_proxy(current_proxy) if current_proxy else None,
                            timeout=15
                        )
                        request_count += 1

                        # 403 处理逻辑
                        if response.status_code == 403:
                            if not current_proxy:
                                print("\n⚠️ 访问被拒绝（403），可能触发防护机制")
                                sys.exit(1)
                            else:
                                print(f"代理 {current_proxy} 返回403，继续尝试其他代理...")
                                available_proxies.remove(current_proxy)
                                if available_proxies:
                                    proxy_index = proxy_index % len(available_proxies)
                                    current_proxy = available_proxies[proxy_index]
                                    print(f"切换到新代理：{current_proxy}")
                                    continue
                                else:
                                    print("所有代理均已失效，正在保存数据并退出...")
                                    sys.exit(1)

                        # 处理响应数据
                        if response.status_code == 200:
                            response_data = response.json()
                            if response_data.get("code") == 401:
                                auth_manager.update_headers()
                                print("Token已更新，正在重试...")
                                continue
                            
                            if response_data.get("success"):
                                all_results[query_type].extend(process_response(response_data, service_type))
                                success = True
                                # 智能延时
                                delay = random.uniform(3, 4) if not current_proxy else random.uniform(0.5, 1.5)
                                time.sleep(delay)
                                print(f"请求成功，随机延迟: {delay:.2f}秒")
                            else:
                                raise Exception(f"API返回错误：{response_data.get('msg')}")
                        else:
                            raise Exception(f"HTTP错误代码：{response.status_code}")

                    except Exception as e:
                        print(f"请求失败：{str(e)}")
                        if current_proxy:
                            if current_proxy in available_proxies:
                                available_proxies.remove(current_proxy)
                                print(f"移除失效代理：{current_proxy}")
                            if available_proxies:
                                proxy_index = proxy_index % len(available_proxies)
                                current_proxy = available_proxies[proxy_index]
                                print(f"切换到新代理：{current_proxy}")
                                continue
                            else:
                                print("所有代理均已失效，正在保存数据并退出...")
                                sys.exit(1)
                        else:
                            print("未使用代理，请求失败，正在保存数据并退出...")
                            sys.exit(1)

                if not success:
                    print(f"{query_type} 类型查询失败")
                    
    except KeyboardInterrupt:
        print("\n操作中断，正在保存数据...")
    finally:
        write_to_excel(all_results, args.output)



def format_proxy(proxy_str):
    """格式化代理地址，自动识别代理类型"""
    if proxy_str.startswith("socks5://"):
        return {"http": proxy_str, "https": proxy_str}
    elif proxy_str.startswith("http://"):
        return {"http": proxy_str, "https": proxy_str}
    return proxy_str


def validate_proxies(proxies):
    """简单验证代理格式有效性"""
    valid_proxies = []
    for p in proxies:
        if p.startswith(("http://", "https://", "socks5://")):
            valid_proxies.append(p)
        else:
            print(f"忽略无效代理格式：{p}")
    return valid_proxies


def load_units(args):
    """加载查询单位列表"""
    if args.file:
        with open(args.file, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip()]
    elif args.unit_name:
        return [args.unit_name]
    return []


if __name__ == '__main__':
    main()
