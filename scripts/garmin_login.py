"""一次性 Garmin 登入：互動輸入密碼/MFA，輸出加密權杖。"""

import getpass
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet
from garminconnect import Garmin

from garmin_crypto import encrypt_file


ROOT = Path(__file__).resolve().parents[1]
ENCRYPTED_TOKEN = ROOT / "data" / "garmin-tokens.enc"


def main():
    if sys.version_info < (3, 12):
        raise SystemExit("需要 Python 3.12 以上；請先安裝後再執行此程式。")

    email = input("Garmin 帳號 Email：").strip()
    if not email:
        raise SystemExit("Email 不可空白")
    password = getpass.getpass("Garmin 密碼（不會顯示或儲存）：")
    if not password:
        raise SystemExit("密碼不可空白")

    key = os.getenv("GARMIN_TOKEN_KEY", "").strip()
    if not key:
        key = Fernet.generate_key().decode("ascii")

    with tempfile.TemporaryDirectory(prefix="garmin-auth-") as temp_dir:
        print("正在登入 Garmin Connect…")
        client = Garmin(
            email,
            password,
            prompt_mfa=lambda: input("Garmin MFA 驗證碼：").strip(),
        )
        client.login(temp_dir)
        client.client.dump(temp_dir)
        token_file = Path(temp_dir) / "garmin_tokens.json"
        if not token_file.exists():
            raise RuntimeError("登入成功，但找不到 Garmin 權杖檔")
        encrypt_file(token_file, ENCRYPTED_TOKEN, key)

    print("\n登入成功，已建立：", ENCRYPTED_TOKEN)
    print("請在 GitHub Repository secret 建立 GARMIN_TOKEN_KEY，值如下：")
    print(key)
    print("\n請勿將上面的 key 貼到聊天、README 或公開程式碼。")

    print("\n正在執行第一次完整同步，請稍候…")
    sync_env = os.environ.copy()
    sync_env["GARMIN_TOKEN_KEY"] = key
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "garmin_sync.py"), "--fetch-all"],
        cwd=ROOT,
        env=sync_env,
        check=True,
    )
    print("首次同步完成。重新整理 strava_halo.html 即可看到 Garmin 活動。")


if __name__ == "__main__":
    main()
