"""
Migração: Cria tabelas para instalação remota de pacotes.

Uso:
    python migrate_packages.py

Segurança:
    - Verifica se as tabelas já existem antes de criar.
    - Não altera dados existentes.
    - Pode ser executado múltiplas vezes sem efeito colateral.
"""
import sqlite3
import os
import sys


def get_db_path():
    """Retorna o caminho do banco de dados."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, 'data', 'database.db')


def migrate():
    """Executa a migração de forma segura."""
    db_path = get_db_path()

    if not os.path.exists(db_path):
        print(f"[MIGRAÇÃO] ERRO: Banco de dados não encontrado em: {db_path}")
        print("[MIGRAÇÃO] Execute a aplicação pelo menos uma vez para criar o banco.")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Verifica tabelas existentes
        tables = [t[0] for t in cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]

        # --- Tabela package_jobs ---
        if 'package_jobs' not in tables:
            cursor.execute("""
                CREATE TABLE package_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    completed_at DATETIME,
                    package_name VARCHAR(100) NOT NULL,
                    package_type VARCHAR(20) DEFAULT 'debian',
                    version VARCHAR(50),
                    requested_by VARCHAR(80) NOT NULL,
                    status VARCHAR(30) DEFAULT 'resolving',
                    total_nodes INTEGER DEFAULT 0,
                    success_nodes INTEGER DEFAULT 0,
                    failed_nodes INTEGER DEFAULT 0,
                    offline_nodes INTEGER DEFAULT 0,
                    skipped_nodes INTEGER DEFAULT 0,
                    error_message TEXT,
                    cache_hit BOOLEAN DEFAULT 0,
                    total_debs INTEGER DEFAULT 0,
                    total_size_bytes INTEGER DEFAULT 0
                )
            """)
            conn.commit()
            print("[MIGRAÇÃO] ✓ Tabela 'package_jobs' criada com sucesso.")
        else:
            print("[MIGRAÇÃO] ✓ Tabela 'package_jobs' já existe. Nada a fazer.")

        # --- Tabela package_job_nodes ---
        if 'package_job_nodes' not in tables:
            cursor.execute("""
                CREATE TABLE package_job_nodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL,
                    node_ip VARCHAR(15) NOT NULL,
                    status VARCHAR(20) DEFAULT 'pending',
                    message TEXT,
                    started_at DATETIME,
                    completed_at DATETIME,
                    node_arch VARCHAR(20),
                    node_os VARCHAR(100),
                    FOREIGN KEY (job_id) REFERENCES package_jobs(id)
                )
            """)
            conn.commit()
            print("[MIGRAÇÃO] ✓ Tabela 'package_job_nodes' criada com sucesso.")
        else:
            print("[MIGRAÇÃO] ✓ Tabela 'package_job_nodes' já existe. Nada a fazer.")

        # Mostra estado atual
        try:
            cursor.execute("SELECT COUNT(*) FROM package_jobs")
            total_jobs = cursor.fetchone()[0]
            print(f"[MIGRAÇÃO] Estado atual: {total_jobs} jobs no banco.")
        except sqlite3.OperationalError:
            pass

    except Exception as e:
        print(f"[MIGRAÇÃO] ERRO: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == '__main__':
    print("[MIGRAÇÃO] Pacotes — Criando tabelas package_jobs e package_job_nodes")
    print(f"[MIGRAÇÃO] Banco: {get_db_path()}")
    print("---")
    migrate()
    print("---")
    print("[MIGRAÇÃO] Concluído.")
