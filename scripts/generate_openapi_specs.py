#!/usr/bin/env python3
"""
OpenAPI 规范自动生成脚本
从运行的 FastAPI 微服务拉取 /openapi.json 并保存为静态文件。
用于 CI/CD pipeline 或开发环境快速更新 spec。

用法:
  python3 scripts/generate_openapi_specs.py
  python3 scripts/generate_openapi_specs.py --output docs/api --services 8000:strategy 8001:execution 8002:scheduler
"""

import json
import os
import sys
from urllib.request import urlopen, Request
from urllib.error import URLError

DEFAULT_SERVICES = [
    (8000, 'strategy-service', '策略研究服务'),
    (8001, 'execution-service', '交易执行服务'),
    (8002, 'ai-scheduler', 'AI调度器'),
]


def fetch_openapi(port: int, host: str = 'http://localhost') -> dict:
    """从运行的 FastAPI 服务获取 OpenAPI 规范"""
    url = f"{host}:{port}/openapi.json"
    req = Request(url, headers={'Accept': 'application/json'})
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def generate_specs(output_dir: str = None, host: str = 'http://localhost'):
    """为主干生成并保存 OpenAPI 规范"""
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    for port, name, label in DEFAULT_SERVICES:
        filename = f"{name}.json"
        path = os.path.join(output_dir, filename) if output_dir else filename

        try:
            print(f"⏳ 正在获取 {label} (:{port})...", end=' ')
            spec = fetch_openapi(port, host)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(spec, f, ensure_ascii=False, indent=2)
            endpoints = len(spec.get('paths', {}))
            print(f"✅ {endpoints} 个端点 -> {path}")
        except URLError as e:
            print(f"❌ 连接失败: {e.reason}")
        except Exception as e:
            print(f"❌ 错误: {e}")

    print("\n✨ OpenAPI 规范生成完成!")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='生成 QuantTradingSystem OpenAPI 规范')
    parser.add_argument('--output', '-o', default='docs/api',
                        help='输出目录 (默认: docs/api)')
    parser.add_argument('--host', default='http://localhost',
                        help='微服务主机地址 (默认: http://localhost)')
    parser.add_argument('--prod', action='store_true',
                        help='生产模式 (使用 Docker 内部 hostname)')
    args = parser.parse_args()

    if args.prod:
        args.host = 'http://strategy-service'  # 在 Docker 网络内部用服务名

    generate_specs(output_dir=args.output, host=args.host)
