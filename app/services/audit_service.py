import os
import logging
from datetime import datetime
from app.config import Config

class AuditService:
    @staticmethod
    def _ensure_dir():
        if not os.path.exists(Config.LOG_DIR):
            os.makedirs(Config.LOG_DIR)

    @staticmethod
    def log_action(username: str, action: str, details: str):
        AuditService._ensure_dir()
        filepath = os.path.join(Config.LOG_DIR, f"{username}.log")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        entry = f"[{timestamp}] ACTION: {action} | DETAILS: {details}\n"
        
        try:
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write(entry)
        except Exception as e:
            logging.error(f"Falha ao gravar log de auditoria: {e}")

    @staticmethod
    def get_logs(username: str):
        AuditService._ensure_dir()
        filepath = os.path.join(Config.LOG_DIR, f"{username}.log")
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        return "Nenhum registro encontrado."
        
    @staticmethod
    def list_log_users():
        AuditService._ensure_dir()
        return [f.replace('.log', '') for f in os.listdir(Config.LOG_DIR) if f.endswith('.log')]
