"""Usage: python scripts/create_admin.py admin@example.com password123"""
import asyncio
import sys

from app.core.security import hash_password
from app.database.models import User
from app.database.session import AsyncSessionLocal, init_db


async def main(email: str, password: str) -> None:
    await init_db()
    async with AsyncSessionLocal() as db:
        existing = await db.execute(
            __import__("sqlalchemy").select(User).where(User.email == email)
        )
        if existing.scalar_one_or_none():
            print(f"User {email} already exists.")
            return
        db.add(User(
            email=email, password_hash=hash_password(password), role="admin",
        ))
        await db.commit()
        print(f"Admin user {email} created.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python scripts/create_admin.py EMAIL PASSWORD")
        sys.exit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
