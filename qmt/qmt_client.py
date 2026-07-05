#!/usr/bin/env python3
"""
QMT Bridge Client — Mac端调用Windows QMT桥接服务。

用法：
    python qmt_client.py health
    python qmt_client.py account
    python qmt_client.py positions
    python qmt_client.py quote 000001.SZ
    python qmt_client.py buy 000001.SZ 12.50 100

配置：环境变量 QMT_BRIDGE_URL 设置桥接地址
      默认 http://{windows_ip}:8580
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import requests


class QMTBridgeClient:
    """Mac端QMT桥接客户端"""

    def __init__(self, base_url: str | None = None):
        self.base_url = (
            base_url or os.environ.get("QMT_BRIDGE_URL") or "http://localhost:8580"
        ).rstrip("/")
        self.session = requests.Session()
        self.session.timeout = 10

    def _get(self, path: str, params: dict | None = None) -> Any:
        resp = self.session.get(f"{self.base_url}{path}", params=params)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, json_data: dict) -> Any:
        resp = self.session.post(f"{self.base_url}{path}", json=json_data)
        resp.raise_for_status()
        return resp.json()

    def health(self) -> dict:
        return self._get("/health")

    def quote(self, code: str) -> dict:
        return self._get(f"/quote/{code}")

    def quotes(self, codes: list[str]) -> dict:
        return self._get("/quotes", {"codes": ",".join(codes)})

    def account(self) -> dict:
        return self._get("/account")

    def positions(self) -> dict:
        return self._get("/positions")

    def buy(self, code: str, price: float, quantity: int, order_type: str = "LIMIT") -> dict:
        return self._post(
            "/buy",
            {
                "code": code,
                "price": price,
                "quantity": quantity,
                "order_type": order_type,
            },
        )

    def sell(self, code: str, price: float, quantity: int, order_type: str = "LIMIT") -> dict:
        return self._post(
            "/sell",
            {
                "code": code,
                "price": price,
                "quantity": quantity,
                "order_type": order_type,
            },
        )

    def cancel(self, order_id: int) -> dict:
        return self._post(f"/cancel/{order_id}", {})

    def orders(self) -> dict:
        return self._get("/orders")


def main():
    if len(sys.argv) < 2:
        print("用法: python qmt_client.py <command> [args...]")
        print()
        print("命令:")
        print("  health                    健康检查")
        print("  account                   查询账户")
        print("  positions                 查询持仓")
        print("  quote <code>              查询行情 (如 000001.SZ)")
        print("  quotes <c1,c2>            批量查询行情")
        print("  buy <code> <price> <qty>  买入 (price=0为市价)")
        print("  sell <code> <price> <qty> 卖出")
        print("  orders                    查询委托")
        print("  cancel <order_id>         撤单")
        print()
        url = os.environ.get("QMT_BRIDGE_URL", "http://localhost:8580")
        print(f"桥接地址: {url} (可通过环境变量 QMT_BRIDGE_URL 修改)")
        sys.exit(0)

    client = QMTBridgeClient()
    cmd = sys.argv[1]

    try:
        if cmd == "health":
            result = client.health()
        elif cmd == "account":
            result = client.account()
        elif cmd == "positions":
            result = client.positions()
        elif cmd == "quote":
            result = client.quote(sys.argv[2])
        elif cmd == "quotes":
            result = client.quotes(sys.argv[2].split(","))
        elif cmd == "buy":
            result = client.buy(sys.argv[2], float(sys.argv[3]), int(sys.argv[4]))
        elif cmd == "sell":
            result = client.sell(sys.argv[2], float(sys.argv[3]), int(sys.argv[4]))
        elif cmd == "orders":
            result = client.orders()
        elif cmd == "cancel":
            result = client.cancel(int(sys.argv[2]))
        else:
            print(f"未知命令: {cmd}")
            sys.exit(1)

        print(json.dumps(result, ensure_ascii=False, indent=2))
    except requests.exceptions.ConnectionError:
        print(f"❌ 连接失败: {client.base_url}")
        print("请确认:")
        print("  1. Windows PC上QMT桥接服务已启动")
        print("  2. 防火墙允许端口8580")
        print("  3. 环境变量 QMT_BRIDGE_URL 指向正确地址")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
