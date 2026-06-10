[1mdiff --git a/app/routes/main.py b/app/routes/main.py[m
[1mindex 9274e7c..4d1f582 100644[m
[1m--- a/app/routes/main.py[m
[1m+++ b/app/routes/main.py[m
[36m@@ -5,6 +5,8 @@[m [mfrom app.services.ansible_service import AnsibleService[m
 from app.services.audit_service import AuditService[m
 from app.config import Config[m
 from app.models.user import User [m
[32m+[m[32mfrom app.models.node import Node[m
[32m+[m[32mfrom app.services.discovery_service import DiscoveryService[m
 [m
 main_bp = Blueprint('main', __name__)[m
 [m
[36m@@ -22,16 +24,33 @@[m [mdef index():[m
 def status():[m
     """[m
     Rota UNIFICADA para verificar status.[m
[31m-    Aceita GET (load inicial) e POST (refresh forçado).[m
[32m+[m[32m    Fase 3B: Tabela nodes como única fonte de verdade.[m
     """[m
[31m-    # Gera IPs a partir da configuracao (padrao: 10.2.0.1 a 10.2.0.20)[m
[31m-    nodes = [f"{Config.NODE_SUBNET}.{i}" for i in range(Config.NODE_IP_START, Config.NODE_IP_END + 1)][m
[31m-    [m
     try:[m
[31m-        results = AnsibleService.check_nodes_status(nodes)[m
[32m+[m[32m        # Fluxo obrigatório do Reverificar:[m
[32m+[m[32m        # 1. Usuário clica em Reverificar -> POST[m
[32m+[m[32m        # 2. Executa run_scan() -> faz ping sweep e ip neigh -> salva na tabela nodes[m
[32m+[m[32m        if request.method == 'POST':[m
[32m+[m[32m            DiscoveryService.run_scan()[m
[32m+[m[41m            [m
[32m+[m[32m        # Lê a tabela nodes (já com dados atualizados caso tenha sido um POST)[m
[32m+[m[32m        nodes_db = Node.query.all()[m
[32m+[m[41m        [m
[32m+[m[32m        results = [][m
[32m+[m[32m        for node in nodes_db:[m
[32m+[m[32m            nome = node.label if node.label else f"Nó {node.ip.split('.')[-1]}"[m
[32m+[m[32m            results.append({[m
[32m+[m[32m                'nome': nome,[m
[32m+[m[32m                'ip': node.ip,[m
[32m+[m[32m                'online': node.is_online[m
[32m+[m[32m            })[m
[32m+[m[41m            [m
[32m+[m[32m        # Ordenação numérica obrigatória pelo último octeto do IP[m
[32m+[m[32m        results = sorted(results, key=lambda x: int(x['ip'].split('.')[-1]))[m
[32m+[m[41m        [m
         return jsonify({'nodes': results})[m
     except Exception as e:[m
[31m-        return jsonify({'error': 'ansible_execution_failed', 'details': str(e)}), 500[m
[32m+[m[32m        return jsonify({'error': 'status_check_failed', 'details': str(e)}), 500[m
 [m
 @main_bp.route('/api/command', methods=['POST'])[m
 @login_required[m
