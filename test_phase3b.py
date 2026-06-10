"""
Teste Funcional — Fase 3B
Valida:
- Rota /api/status retorna nós ordenados numericamente (1, 2, 10, 11).
- Rota /api/status em POST chama DiscoveryService.run_scan.
- AnsibleService.manage_node_user lê do banco (mock) e não do gerador estático.
"""
import os
import sys
import types
import threading

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

os.environ['DISCOVERY_ENABLED'] = 'false'
os.environ['FLASK_DEBUG'] = '0'

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import current_app
from app import create_app
from app.extensions import db
from app.models.node import Node
from app.config import Config
from app.services.discovery_service import DiscoveryService
from app.services.ansible_service import AnsibleService

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

print("=" * 70)
print("TESTE FUNCIONAL — FASE 3B")
print("=" * 70)

with app.app_context():
    db.create_all()

    # Criação de nós fora de ordem alfabética para testar ordenação numérica
    # 10.2.0.2, 10.2.0.10, 10.2.0.1
    n2 = Node(ip='10.2.0.2', mac='00:00:00:00:00:02', source='discovered', is_online=True)
    n10 = Node(ip='10.2.0.10', mac='00:00:00:00:00:10', source='discovered', is_online=True)
    n1 = Node(ip='10.2.0.1', mac='00:00:00:00:00:01', source='discovered', is_online=False)
    
    db.session.add_all([n2, n10, n1])
    db.session.commit()

# Mock do LoginManager para bypass em @login_required
@app.before_request
def mock_login():
    from flask_login import login_user
    from app.models.user import User
    # Cria um user falso
    if not User.query.filter_by(username='admin').first():
        u = User(username='admin')
        u.set_password('123')
        db.session.add(u)
        db.session.commit()
    user = User.query.filter_by(username='admin').first()
    login_user(user)

client = app.test_client()

# =====================================================
# TESTE 1: Ordenação e leitura da base (GET /api/status)
# =====================================================
print("\n[1] GET /api/status - Leitura da base e ordenação numérica")
res = client.get('/api/status')
test("Status Code 200", res.status_code == 200)

data = res.get_json()
test("Retorna JSON com chave 'nodes'", 'nodes' in data)

nodes = data.get('nodes', [])
test("Retornou 3 nós", len(nodes) == 3)

if len(nodes) == 3:
    test("Primeiro nó é 10.2.0.1 (numérico)", nodes[0]['ip'] == '10.2.0.1')
    test("Segundo nó é 10.2.0.2 (numérico)", nodes[1]['ip'] == '10.2.0.2')
    test("Terceiro nó é 10.2.0.10 (numérico)", nodes[2]['ip'] == '10.2.0.10')
    test("Nó offline mapeado corretamente", nodes[0]['online'] == False)
    test("Nó online mapeado corretamente", nodes[1]['online'] == True)

# =====================================================
# TESTE 2: Comportamento POST /api/status (Reverificar)
# =====================================================
print("\n[2] POST /api/status - Invoca run_scan()")
# Vamos mockar o run_scan para apenas injetar um novo nó na base,
# comprovando que ele foi chamado e que a resposta traz o nó novo.
original_run_scan = DiscoveryService.run_scan
scan_called = False

def mock_run_scan():
    global scan_called
    scan_called = True
    n99 = Node(ip='10.2.0.99', mac='00:00:00:00:00:99', source='discovered', is_online=True)
    db.session.add(n99)
    db.session.commit()

DiscoveryService.run_scan = mock_run_scan

res_post = client.post('/api/status')
test("POST retorna 200", res_post.status_code == 200)
test("DiscoveryService.run_scan foi chamado", scan_called)

data_post = res_post.get_json()
nodes_post = data_post.get('nodes', [])
test("Retornou 4 nós agora", len(nodes_post) == 4)
if len(nodes_post) == 4:
    test("Novo nó (10.2.0.99) foi retornado na última posição", nodes_post[-1]['ip'] == '10.2.0.99')

DiscoveryService.run_scan = original_run_scan

# =====================================================
# TESTE 3: AnsibleService.manage_node_user lê do banco
# =====================================================
print("\n[3] AnsibleService.manage_node_user")

with app.app_context():
    # Temos 4 nós no total: 10.2.0.1 (OFFLINE), .2 (ONLINE), .10 (ONLINE), .99 (ONLINE).
    # manage_node_user deve ignorar o .1 e rodar para os outros 3.
    
    # Injetar spy no _create_inventory para checar os hosts passados
    original_create_inventory = AnsibleService._create_inventory
    inventory_hosts_spy = []
    
    def spy_create_inventory(hosts, user):
        inventory_hosts_spy.extend(hosts)
        return original_create_inventory(hosts, user)
        
    AnsibleService._create_inventory = spy_create_inventory
    
    # Chama o método
    AnsibleService.manage_node_user('testuser', 'present', '123')
    
    test("Apenas 3 hosts passados para o Ansible", len(inventory_hosts_spy) == 3)
    if len(inventory_hosts_spy) == 3:
        test("Host 1 = 10.2.0.2", inventory_hosts_spy[0]['ip'] == '10.2.0.2')
        test("Host 2 = 10.2.0.10", inventory_hosts_spy[1]['ip'] == '10.2.0.10')
        test("Host 3 = 10.2.0.99", inventory_hosts_spy[2]['ip'] == '10.2.0.99')
        # Verifica ordenação e exclusão do nó offline (10.2.0.1)
    
    AnsibleService._create_inventory = original_create_inventory

print("\n" + "=" * 70)
total = len(results)
passed = sum(1 for _, ok in results if ok)
failed = total - passed

if failed == 0:
    print(f"RESULTADO: {PASS} {passed}/{total} testes passaram")
else:
    print(f"RESULTADO: {FAIL} {passed}/{total} passaram, {failed} falharam")

sys.exit(0 if failed == 0 else 1)
