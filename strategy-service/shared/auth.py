"""Auth stub - no auth in dev mode"""
from fastapi import Depends


async def get_current_user():
    return {"id": "dev-user", "name": "Developer"}
