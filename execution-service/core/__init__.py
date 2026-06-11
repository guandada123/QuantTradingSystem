"""Execution Service — Core Domain.

This package contains the core execution logic:
- orders: Order lifecycle management (create, cancel, modify)
- risk: Real-time risk control (single-stock ≤30%, total ≤3 positions, stop-loss 5-10%)
- router: Smart order routing (TWAP/VWAP/Iceberg)
- audit: Transaction logging and compliance audit
"""
