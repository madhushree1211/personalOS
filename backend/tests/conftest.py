import os

os.environ.setdefault("ENV", "test")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-at-least-32-characters")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_personalos.db")
os.environ.setdefault("DEMO_PASSWORD", "test-demo-password")
