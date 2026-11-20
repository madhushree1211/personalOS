import atexit
import os
import shutil
import tempfile

_tmp_dir = tempfile.mkdtemp(prefix="personalos_test_")
atexit.register(shutil.rmtree, _tmp_dir, ignore_errors=True)

os.environ.setdefault("ENV", "test")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-at-least-32-characters")
# Always a fresh, private database per pytest session.
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(_tmp_dir, "test.db").replace("\\", "/")
os.environ.setdefault("DEMO_PASSWORD", "test-demo-password")