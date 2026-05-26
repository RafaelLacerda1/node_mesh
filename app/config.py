import os
from datetime import timedelta

class Config:
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, '..'))
    
    # Seguranca
    SECRET_KEY = os.environ.get("SECRET_KEY", "uma-chave-secreta-bem-segura-padrao")
    
    # --- CONFIGURACAO DE TIMEOUT DA SESSAO ---
    # Define que a sessao expira apos 15 minutos de inatividade
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=15)
    
    # Banco de Dados
    DB_FOLDER = os.path.join(PROJECT_ROOT, 'data')
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", f"sqlite:///{os.path.join(DB_FOLDER, 'database.db')}")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Ansible
    ANSIBLE_DIR = os.path.join(PROJECT_ROOT, 'ansible')
    SSH_KEY_PATH = os.path.join(os.path.expanduser('~'), '.ssh', 'id_rsa')
    
    # WebSSH
    WEBSSH_URL = os.environ.get("WEBSSH_URL", "http://172.30.0.14:8888/")
    
    # Logs
    LOG_DIR = os.path.join(DB_FOLDER, 'logs')
