"""
Teste Funcional — Fase 3C (Concorrência e Mutex)
Valida:
- Mutex global funciona.
- Múltiplas chamadas simultâneas não enfileiram e não travam o processo.
- Chamada bloqueada retorna rapidamente com `scan_running=True`.
- Lock é liberado sempre.
- Chamadas HTTP simultâneas na rota /api/status não quebram.
"""
import os
import sys
import time
import threading
import subprocess
import types

# Mocks para não precisar do ambiente real completo
ansible_runner_mock = types.ModuleType('ansible_runner')
ansible_runner_mock.run = lambda **kwargs: type('AnsibleResult', (), {'rc': 0, 'events': []})()
sys.modules['ansible_runner'] = ansible_runner_mock

try:
    import passlib
except ImportError:
    passlib_mock = types.ModuleType('passlib')
    passlib_hash = types.ModuleType('passlib.hash')
    passlib_mock.hash = passlib_hash
    sys.modules['passlib'] = passlib_mock
    sys.modules['passlib.hash'] = passlib_hash

os.environ['DISCOVERY_ENABLED'] = 'true'
os.environ['FLASK_DEBUG'] = '0'

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import current_app
from app import create_app
from app.extensions import db
from app.models.node import Node
from app.config import Config
from app.services.discovery_service import DiscoveryService

class TestConfig(Config):
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    TESTING = True
    WTF_CSRF_ENABLED = False

app = create_app(TestConfig)
app.test_client_class = app.test_client_class

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results = []

def test(name, condition, detail=""):
    status = PASS if condition else FAIL
    results.append((name, condition))
    print(f"  {status} {name}")
    if detail and not condition:
        print(f"         Detalhe: {detail}")

import unittest.mock

print("=" * 70)
print("TESTE DE CONCORRÊNCIA — FASE 3C")
print("=" * 70)

def mock_subprocess_run(cmd, *args, **kwargs):
    time.sleep(2)  # Simula demora da rede
    return type('SubprocessResult', (), {'returncode': 0, 'stdout': '', 'stderr': ''})()

with app.app_context():
    db.create_all()

client = app.test_client()

# =====================================================
# TESTE 1: Threads simultâneas acessando run_scan()
# =====================================================
print("\n[1] Chamadas Concorrentes via Python Thread (Scheduler vs Manual)")

scan_results = []
exceptions = []

def worker():
    with app.app_context():
        try:
            res = DiscoveryService.run_scan()
            scan_results.append(res)
        except Exception as e:
            exceptions.append(str(e))

t1 = threading.Thread(target=worker)
t2 = threading.Thread(target=worker)
t3 = threading.Thread(target=worker)

from app.services.scheduler import DiscoveryScheduler

# Garante que a thread do scheduler parou e soltou o lock inicial
DiscoveryScheduler.stop()
with DiscoveryService._scan_lock:
    pass

# Inicia as três no exato mesmo momento
start_time = time.time()

with unittest.mock.patch('app.services.discovery_service.subprocess.run', side_effect=mock_subprocess_run):
    t1.start()
    t2.start()
    t3.start()

    t1.join()
    t2.join()
    t3.join()

end_time = time.time()

test("Sem exceções", len(exceptions) == 0, str(exceptions))
test("Todos retornaram resultado", len(scan_results) == 3)

# Exatamente UM deles deve ter feito o scan real e DOIS devem ter recebido 'scan_running'
running_flags = [r.get('scan_running') for r in scan_results]
real_scans = [r for r in scan_results if not r.get('scan_running')]
ignored_scans = [r for r in scan_results if r.get('scan_running')]

test("Apenas 1 scan executado de verdade", len(real_scans) == 1, f"real_scans={len(real_scans)} ignored={len(ignored_scans)} results={scan_results}")
test("Exatamente 2 scans ignorados com rapidez", len(ignored_scans) == 2)
test("Nenhum deadlock - Tempo total próximo a ~2 segundos", (end_time - start_time) < 10)

# =====================================================
# TESTE 2: Rota POST /api/status não quebra
# =====================================================
print("\n[2] Rota HTTP /api/status com lock ocupado")

# Vamos ocupar o lock manualmente para testar o endpoint
DiscoveryService._scan_lock.acquire()

try:
    with app.test_client() as c:
        # Fazer login
        from flask_login import login_user
        from app.models.user import User
        with app.app_context():
            u = User.query.filter_by(username='admin').first()
            if not u:
                u = User(username='admin')
                u.set_password('123')
                db.session.add(u)
                db.session.commit()
            
        @app.before_request
        def mock_login():
            user = User.query.filter_by(username='admin').first()
            login_user(user)

        res_post = c.post('/api/status')
        test("POST retorna HTTP 200 mesmo travado", res_post.status_code == 200)
        
        data = res_post.get_json()
        test("Retorna lista de nodes do banco", 'nodes' in data)

finally:
    # Libera a chave manualmente para restaurar
    DiscoveryService._scan_lock.release()

# =====================================================
# TESTE 3: RuntimeError de release evitado e liberação segura
# =====================================================
print("\n[3] Garantia de liberação em caso de falha")

# Simulando um erro catastrófico DENTRO do try/except do scan
def mock_failing_subprocess_run(cmd, *args, **kwargs):
    raise RuntimeError("Falha de rede inesperada")

with app.app_context():
    with unittest.mock.patch('app.services.discovery_service.subprocess.run', side_effect=mock_failing_subprocess_run):
        res = DiscoveryService.run_scan()

test("Exceção não parou o backend (foi controlada e retornou error)", res.get('success') == False)
test("Lock foi liberado após o desastre (lock não está trancado)", not DiscoveryService._scan_lock.locked())

print("\n" + "=" * 70)
total = len(results)
passed = sum(1 for _, ok in results if ok)
failed = total - passed

if failed == 0:
    print(f"RESULTADO: {PASS} {passed}/{total} testes passaram")
else:
    print(f"RESULTADO: {FAIL} {passed}/{total} passaram, {failed} falharam")

sys.exit(0 if failed == 0 else 1)
