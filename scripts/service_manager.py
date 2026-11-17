"""
VİOP Servis Yöneticisi ve Otomatik Başlatıcı (scripts/service_manager.py).
Bilgisayar açıldığında veya manuel tıklandığında hem arka plan otonom operatörünü
hem de Streamlit canlı kokpitini denetler, kapalı olanları otomatik başlatır.
"""

import os
import socket
import subprocess
import sys
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(PROJECT_ROOT)

def is_port_in_use(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
            return False
    except OSError:
        return True
    except Exception:
        return False

def ensure_services_running():
    # 1. Otonom Operatör (Port 58999 kilit soketi)
    if not is_port_in_use(58999):
        print("[*] Otonom Operatör başlatılıyor...")
        subprocess.Popen(
            [sys.executable, "-m", "src.execution.autonomous_operator"],
            cwd=PROJECT_ROOT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | (subprocess.DETACHED_PROCESS if os.name == "nt" else 0)
        )
        time.sleep(1.0)
    else:
        print("[+] Otonom Operatör zaten çalışıyor.")

    # 2. Streamlit Dashboard (Port 8501)
    if not is_port_in_use(8501):
        print("[*] Streamlit Dashboard başlatılıyor (Port 8501)...")
        subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", "src/dashboard/app.py", "--server.port", "8501", "--server.headless", "true", "--theme.base", "dark"],
            cwd=PROJECT_ROOT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | (subprocess.DETACHED_PROCESS if os.name == "nt" else 0)
        )
        time.sleep(2.0)
    else:
        print("[+] Streamlit Dashboard zaten çalışıyor.")

if __name__ == "__main__":
    ensure_services_running()
