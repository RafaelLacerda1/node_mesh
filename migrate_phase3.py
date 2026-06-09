"""
Migração Fase 3A: Adiciona coluna missed_scans à tabela nodes.

Uso:
    python migrate_phase3.py

Segurança:
    - Verifica se a coluna já existe antes de adicionar.
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
        # Verifica se a tabela nodes existe
        tables = [t[0] for t in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        if 'nodes' not in tables:
            print("[MIGRAÇÃO] ERRO: Tabela 'nodes' não existe.")
            print("[MIGRAÇÃO] Execute a aplicação pelo menos uma vez para criar as tabelas.")
            sys.exit(1)

        # Verifica colunas existentes na tabela nodes
        cursor.execute("PRAGMA table_info(nodes)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'missed_scans' not in columns:
            cursor.execute("ALTER TABLE nodes ADD COLUMN missed_scans INTEGER DEFAULT 0")
            conn.commit()
            print("[MIGRAÇÃO] ✓ Coluna 'missed_scans' adicionada com sucesso.")
            print(f"[MIGRAÇÃO] Banco atualizado: {db_path}")
        else:
            print("[MIGRAÇÃO] ✓ Coluna 'missed_scans' já existe. Nada a fazer.")

        # Mostra estado atual
        cursor.execute("SELECT COUNT(*) FROM nodes")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM nodes WHERE is_online = 1")
        online = cursor.fetchone()[0]
        print(f"[MIGRAÇÃO] Estado atual: {total} nós no banco ({online} online)")

    except Exception as e:
        print(f"[MIGRAÇÃO] ERRO: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == '__main__':
    print("[MIGRAÇÃO] Fase 3A — Adicionando coluna missed_scans")
    print(f"[MIGRAÇÃO] Banco: {get_db_path()}")
    print("---")
    migrate()
    print("---")
    print("[MIGRAÇÃO] Concluído.")
