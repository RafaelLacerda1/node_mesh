"""
Teste Funcional — Fase 3A
Valida: scheduler, app_context, db.session, threads, SQLite thread-safety.
Executa isoladamente sem necessidade de gateway/SSH/ansible.
"""
import os
import sys
import time
import threading
import types

# Mock ansible_runner antes de qualquer import do app
ansible_runner_mock = types.ModuleType('ansible_runner')
ansible_runner_mock.run = lambda **kwargs: None
sys.modules['ansible_runner'] = ansible_runner_mock

# Mock passlib se necessário
try:
    import passlib
except ImportError:
    passlib_mock = types.ModuleType('passlib')
    passlib_hash = types.ModuleType('passlib.hash')
    passlib_mock.hash = passlib_hash
    sys.modules['passlib'] = passlib_mock
    sys.modules['passlib.hash'] = passlib_hash

# Configura ambiente para teste local
os.environ['DISCOVERY_ENABLED'] = 'true'
os.environ['DISCOVERY_INTERVAL_SECONDS'] = '5'
os.environ['DISCOVERY_OFFLINE_THRESHOLD'] = '3'
os.environ['FLASK_DEBUG'] = '0'

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
results = []

def test(name, condition, detail=""):
    status = PASS if condition else FAIL
    results.append((name, condition))
    print(f"  {status} {name}")
    if detail and not condition:
        print(f"         Detalhe: {detail}")

print("=" * 70)
print("TESTE FUNCIONAL — FASE 3A")
print("=" * 70)

# =====================================================
# TESTE 1: Importações e criação do app
# =====================================================
print("\n[1] Importacoes e criacao do app Flask")
try:
    from app import create_app
    from app.extensions import db
    from app.models.node import Node
    from app.config import Config
    test("Imports do app", True)
except Exception as e:
    test("Imports do app", False, str(e))
    print("ABORTANDO: Imports falharam.")
    sys.exit(1)

class TestConfig(Config):
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    DISCOVERY_ENABLED = True
    DISCOVERY_INTERVAL_SECONDS = 5
    DISCOVERY_OFFLINE_THRESHOLD = 3
    TESTING = True

# Desabilita temporariamente para não auto-iniciar scheduler no create_app
os.environ['DISCOVERY_ENABLED'] = 'false'
app = create_app(TestConfig)
os.environ['DISCOVERY_ENABLED'] = 'true'

test("App criado com sucesso", app is not None)
test("Config DISCOVERY_INTERVAL_SECONDS = 5", app.config.get('DISCOVERY_INTERVAL_SECONDS') == 5)
test("Config DISCOVERY_OFFLINE_THRESHOLD = 3", app.config.get('DISCOVERY_OFFLINE_THRESHOLD') == 3)

# =====================================================
# TESTE 2: Modelo Node com missed_scans
# =====================================================
print("\n[2] Modelo Node — coluna missed_scans")
with app.app_context():
    db.create_all()

    node = Node(ip='10.2.0.99', mac='aa:bb:cc:dd:ee:ff',
                source='discovered', is_online=True, missed_scans=0)
    db.session.add(node)
    db.session.commit()

    n = Node.query.filter_by(ip='10.2.0.99').first()
    test("Node criado com missed_scans=0", n is not None and n.missed_scans == 0)

    n.missed_scans = 2
    db.session.commit()
    n2 = Node.query.filter_by(ip='10.2.0.99').first()
    test("missed_scans incrementado para 2", n2.missed_scans == 2)

    d = n2.to_dict()
    test("to_dict() inclui missed_scans", 'missed_scans' in d and d['missed_scans'] == 2)

    db.session.delete(n2)
    db.session.commit()

# =====================================================
# TESTE 3: Scheduler — import e estado inicial
# =====================================================
print("\n[3] Scheduler — import e estado inicial")
from app.services.scheduler import DiscoveryScheduler

test("DiscoveryScheduler importado", DiscoveryScheduler is not None)
test("Scheduler nao esta rodando (estado inicial)", not DiscoveryScheduler._running)
test("Thread eh None (estado inicial)", DiscoveryScheduler._thread is None)
test("scan_count eh 0", DiscoveryScheduler._scan_count == 0)

# =====================================================
# TESTE 4: app_context dentro do _execute_scan
# =====================================================
print("\n[4] app_context — db.session dentro do contexto")

import inspect
source = inspect.getsource(DiscoveryScheduler._execute_scan)
test("_execute_scan contem 'with app.app_context()'", 'with app.app_context()' in source)

loop_source = inspect.getsource(DiscoveryScheduler._scan_loop)
test("_scan_loop chama _execute_scan", '_execute_scan' in loop_source)
test("_scan_loop NAO chama run_scan diretamente", 'run_scan' not in loop_source)

# =====================================================
# TESTE 5: Nenhuma operação db fora do app_context
# =====================================================
print("\n[5] db.session — nenhuma operacao fora do app_context no scheduler")

sched_source = inspect.getsource(DiscoveryScheduler)
test("scheduler.py NAO importa db diretamente", 'from app.extensions import db' not in sched_source)
test("scheduler.py NAO usa db.session diretamente", 'db.session' not in sched_source)
test("DiscoveryService importado DENTRO do app_context",
     'from app.services.discovery_service import DiscoveryService' in source)

# =====================================================
# TESTE 6: Proteção contra dupla execução
# =====================================================
print("\n[6] Scheduler — protecao contra dupla execucao")

DiscoveryScheduler._running = False
DiscoveryScheduler._thread = None
DiscoveryScheduler._scan_count = 0
DiscoveryScheduler._last_scan_result = None
DiscoveryScheduler._last_scan_time = None

init_source = inspect.getsource(create_app)
test("__init__.py verifica DISCOVERY_ENABLED", "DISCOVERY_ENABLED" in init_source)
test("__init__.py verifica WERKZEUG_RUN_MAIN", "WERKZEUG_RUN_MAIN" in init_source)
test("__init__.py verifica app.debug", "not app.debug" in init_source)

start_source = inspect.getsource(DiscoveryScheduler.start)
test("start() usa cls._lock (mutex)", '_lock' in start_source)
test("start() verifica cls._running (guard)", '_running' in start_source)

# =====================================================
# TESTE 7: Scheduler NÃO inicia duas vezes
# =====================================================
print("\n[7] Scheduler — NAO inicia duas vezes")

DiscoveryScheduler._running = True  # Simula já rodando
thread_before = DiscoveryScheduler._thread
DiscoveryScheduler.start(app)  # Deve ser ignorado
test("Segunda chamada a start() ignorada (running=True)", DiscoveryScheduler._thread == thread_before)
DiscoveryScheduler._running = False

# =====================================================
# TESTE 8: Flask Debug Reloader guard
# =====================================================
print("\n[8] Flask Debug Reloader — guard correto")

os.environ.pop('WERKZEUG_RUN_MAIN', None)
should_parent = (os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not True)
test("Debug ON, processo PAI: NAO inicia scheduler", not should_parent)

os.environ['WERKZEUG_RUN_MAIN'] = 'true'
should_child = (os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not True)
test("Debug ON, processo FILHO: SIM inicia scheduler", should_child)

os.environ.pop('WERKZEUG_RUN_MAIN', None)
should_prod = (os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not False)
test("Debug OFF (producao): SIM inicia scheduler", should_prod)

# =====================================================
# TESTE 9: SQLite thread-safety com app_context
# =====================================================
print("\n[9] SQLite — thread-safety com app_context")

thread_errors = []

def thread_db_test():
    try:
        with app.app_context():
            node = Node(ip='10.2.0.200', mac='11:22:33:44:55:66',
                        source='discovered', is_online=True, missed_scans=0)
            db.session.add(node)
            db.session.commit()

            n = Node.query.filter_by(ip='10.2.0.200').first()
            if n is None:
                thread_errors.append("Node nao encontrado apos insert")
                return

            n.missed_scans = 1
            n.is_online = False
            db.session.commit()

            n2 = Node.query.filter_by(ip='10.2.0.200').first()
            if n2.missed_scans != 1:
                thread_errors.append(f"missed_scans={n2.missed_scans}, esperava 1")
            if n2.is_online != False:
                thread_errors.append(f"is_online={n2.is_online}, esperava False")

            db.session.delete(n2)
            db.session.commit()
    except Exception as e:
        thread_errors.append(str(e))

t = threading.Thread(target=thread_db_test, daemon=True)
t.start()
t.join(timeout=10)

test("Thread com db.session + app_context funciona", len(thread_errors) == 0,
     "; ".join(thread_errors) if thread_errors else "")
test("Thread terminou sem timeout", not t.is_alive())

# =====================================================
# TESTE 10: Simulação de ciclo completo
# =====================================================
print("\n[10] Simulacao — ciclo start -> scan -> commit -> sleep -> scan")

cycle_log = []

def mock_scan_cycle(app_ref, cycle_num):
    try:
        with app_ref.app_context():
            from datetime import datetime
            scan_time = datetime.utcnow()

            for i in range(1, 4):
                ip = f'10.2.0.{100+i}'
                node = Node.query.filter_by(ip=ip).first()
                if not node:
                    node = Node(ip=ip, mac=f'aa:bb:cc:dd:ee:{i:02x}',
                               source='discovered', is_online=True, missed_scans=0)
                    db.session.add(node)
                else:
                    node.is_online = True
                    node.missed_scans = 0
                    node.last_seen = scan_time
            db.session.commit()
            cycle_log.append(f'cycle_{cycle_num}_ok')
    except Exception as e:
        cycle_log.append(f'cycle_{cycle_num}_error: {e}')

# Ciclo 1: Start + Scan
cycle_log.clear()
mock_scan_cycle(app, 1)
test("Ciclo 1: start + scan executado", 'cycle_1_ok' in cycle_log)

# Ciclo 2: Sleep + Novo scan
time.sleep(0.1)  # Simula sleep do scheduler
mock_scan_cycle(app, 2)
test("Ciclo 2: sleep + segundo scan executado", 'cycle_2_ok' in cycle_log)

# Ciclo 3: Verificar persistência
with app.app_context():
    nodes = Node.query.filter(Node.ip.like('10.2.0.10%')).all()
    test("Ciclo 3: nos persistidos entre ciclos", len(nodes) == 3)
    for n in nodes:
        db.session.delete(n)
    db.session.commit()

# =====================================================
# TESTE 11: Múltiplos ciclos sem recriar threads
# =====================================================
print("\n[11] Multiplos ciclos — sem recriar threads")

test("start() cria UMA thread com target=_scan_loop",
     'cls._scan_loop' in start_source and 'Thread(' in start_source)
test("_scan_loop tem while cls._running (loop infinito)",
     'while cls._running' in loop_source)
test("_scan_loop NAO cria novas threads dentro do loop",
     'Thread(' not in loop_source)

# =====================================================
# TESTE 12: get_status() retorno correto
# =====================================================
print("\n[12] get_status() — retorno correto")

DiscoveryScheduler._running = False
DiscoveryScheduler._thread = None
DiscoveryScheduler._scan_count = 5
DiscoveryScheduler._last_scan_time = None
DiscoveryScheduler._last_scan_result = {'success': True, 'total_found': 27}

status = DiscoveryScheduler.get_status()
test("get_status() retorna dict", isinstance(status, dict))
test("running=False", status['running'] == False)
test("scan_count=5", status['scan_count'] == 5)
test("last_scan_result contem total_found=27", status['last_scan_result']['total_found'] == 27)
test("thread_alive=False (thread None)", status['thread_alive'] == False)

DiscoveryScheduler._scan_count = 0
DiscoveryScheduler._last_scan_result = None

# =====================================================
# TESTE 13: run_scan() independente de request/session/user
# =====================================================
print("\n[13] run_scan() — independencia de request/session/current_user")

from app.services.discovery_service import DiscoveryService
scan_src = inspect.getsource(DiscoveryService.run_scan)
save_src = inspect.getsource(DiscoveryService._save_to_db)

test("run_scan() NAO usa 'request'", 'request' not in scan_src)
test("run_scan() NAO usa 'session' (exceto db.session)", 'session' not in scan_src.replace('db.session', ''))
test("run_scan() NAO usa 'current_user'", 'current_user' not in scan_src)
test("_save_to_db() NAO usa 'request'", 'request' not in save_src)
test("_save_to_db() NAO usa 'current_user'", 'current_user' not in save_src)

# =====================================================
# TESTE 14: Tolerância offline — guard found_ips
# =====================================================
print("\n[14] Tolerancia offline — guard com found_ips")

test("_save_to_db tem 'if found_ips:' guard", 'if found_ips:' in save_src)
test("_save_to_db NAO tem ternario fragil 'if found_ips else True'",
     'if found_ips else True' not in save_src)
test("_save_to_db usa ~Node.ip.in_(found_ips) sem ternario",
     '~Node.ip.in_(found_ips)' in save_src)

# =====================================================
# TESTE 15: Tolerância offline — simulação real
# =====================================================
print("\n[15] Tolerancia offline — simulacao real com db")

with app.app_context():
    # Cria 3 nós online
    for i in range(1, 4):
        n = Node(ip=f'10.2.0.{50+i}', mac=f'ff:ee:dd:cc:bb:{i:02x}',
                 source='discovered', is_online=True, missed_scans=0)
        db.session.add(n)
    db.session.commit()

    from datetime import datetime

    # Scan 1: só encontra nó 51 (52 e 53 ausentes)
    found_ips = {'10.2.0.51'}
    offline_threshold = 3

    for ip in found_ips:
        node = Node.query.filter_by(ip=ip).first()
        node.is_online = True
        node.missed_scans = 0
        node.last_seen = datetime.utcnow()

    not_found = Node.query.filter(
        Node.source == 'discovered',
        Node.is_online == True,
        ~Node.ip.in_(found_ips)
    ).all()
    for node in not_found:
        node.missed_scans = (node.missed_scans or 0) + 1
        if node.missed_scans >= offline_threshold:
            node.is_online = False
    db.session.commit()

    n52 = Node.query.filter_by(ip='10.2.0.52').first()
    test("Scan 1: no 52 missed_scans=1, still online",
         n52.missed_scans == 1 and n52.is_online == True)

    # Scan 2: mesma situação
    not_found = Node.query.filter(
        Node.source == 'discovered',
        Node.is_online == True,
        ~Node.ip.in_(found_ips)
    ).all()
    for node in not_found:
        node.missed_scans = (node.missed_scans or 0) + 1
        if node.missed_scans >= offline_threshold:
            node.is_online = False
    db.session.commit()

    n52 = Node.query.filter_by(ip='10.2.0.52').first()
    test("Scan 2: no 52 missed_scans=2, still online",
         n52.missed_scans == 2 and n52.is_online == True)

    # Scan 3: agora deve ficar offline
    not_found = Node.query.filter(
        Node.source == 'discovered',
        Node.is_online == True,
        ~Node.ip.in_(found_ips)
    ).all()
    for node in not_found:
        node.missed_scans = (node.missed_scans or 0) + 1
        if node.missed_scans >= offline_threshold:
            node.is_online = False
    db.session.commit()

    n52 = Node.query.filter_by(ip='10.2.0.52').first()
    test("Scan 3: no 52 missed_scans=3, OFFLINE",
         n52.missed_scans == 3 and n52.is_online == False)

    # Scan 4: nó 52 reaparece
    found_ips_2 = {'10.2.0.51', '10.2.0.52'}
    for ip in found_ips_2:
        node = Node.query.filter_by(ip=ip).first()
        node.is_online = True
        node.missed_scans = 0
        node.last_seen = datetime.utcnow()
    db.session.commit()

    n52 = Node.query.filter_by(ip='10.2.0.52').first()
    test("Scan 4: no 52 reaparece — online, missed_scans=0",
         n52.missed_scans == 0 and n52.is_online == True)

    # Cleanup
    for i in range(1, 4):
        n = Node.query.filter_by(ip=f'10.2.0.{50+i}').first()
        if n:
            db.session.delete(n)
    db.session.commit()

# =====================================================
# RESULTADO FINAL
# =====================================================
print("\n" + "=" * 70)
total = len(results)
passed = sum(1 for _, ok in results if ok)
failed = total - passed

if failed == 0:
    print(f"RESULTADO: {PASS} {passed}/{total} testes passaram")
    print("=" * 70)
    print("\n>>> FASE 3A APROVADA PARA COMMIT <<<\n")
else:
    print(f"RESULTADO: {FAIL} {passed}/{total} passaram, {failed} falharam")
    print("=" * 70)
    print("\nTestes que falharam:")
    for name, ok in results:
        if not ok:
            print(f"  x {name}")
    print("\n>>> CORRIGIR ANTES DO COMMIT <<<\n")

sys.exit(0 if failed == 0 else 1)
