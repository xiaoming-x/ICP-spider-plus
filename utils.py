import pandas as pd
import random
import time
import os


TYPE_MAPPING = {"web": 1, "app": 6, "miniapp": 7}


def get_current_time_filename():
    return f"results_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"


def generate_modern_headers(auth_headers):
    browser_version = random.choice(["124", "123", "122"])
    platform = random.choice(["Windows", "macOS"])
    return {
        "Host": "hlwicpfwc.miit.gov.cn",
        "Sec-Ch-Ua": f"\"Chromium\";v=\"{browser_version}\", \"Google Chrome\";v=\"{browser_version}\", \"Not-A.Brand\";v=\"99\"",
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": f"\"{platform}\"",
        "User-Agent": f"Mozilla/5.0 ({'Windows NT 10.0; Win64; x64' if 'Windows' in platform else 'Macintosh; Intel Mac OS X 10_15_7'}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{browser_version}.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Referer": "https://beian.miit.gov.cn/",
        "Origin": "https://beian.miit.gov.cn"
    } | auth_headers


def process_response(response_data, service_type):
    results = []
    if response_data.get("success"):
        for item in response_data["params"]["list"]:
            result = {
                "unitName": item.get("unitName"),
                "mainLicence": item.get("mainLicence"),
                "serviceLicence": item.get("serviceLicence"),
                "updateRecordTime": item.get("updateRecordTime")
            }
            if service_type == 1:
                result["domain"] = item.get("domain")
            else:
                result.update({
                    "serviceName": item.get("serviceName"),
                    "leaderName": item.get("leaderName"),
                    "mainUnitAddress": item.get("mainUnitAddress")
                })
            results.append(result)
    return results


def write_to_excel(results_dict, output_file=None):
    output_file = output_file or get_current_time_filename()
    has_data = any(bool(data) for data in results_dict.values())
    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        if not has_data:
            pd.DataFrame([["无备案数据"]], columns=["提示"]).to_excel(writer, sheet_name="默认", index=False)
        else:
            for sheet_name, data in results_dict.items():
                if data:
                    df = pd.DataFrame(data)
                    safe_name = sheet_name[:31]
                    df.to_excel(writer, sheet_name=safe_name, index=False)
    print(f"结果已保存至：{output_file}")


# def load_proxies():
#    return [line.strip() for line in open("proxy.txt")] if os.path.exists("proxy.txt") else []

def load_proxies():
    """智能代理加载"""
    try:
        with open('proxy.txt', 'r') as f:
            proxies = [line.strip() for line in f if line.strip()]
            print(f"已加载 {len(proxies)} 个代理")
            return proxies
    except FileNotFoundError:
        return []