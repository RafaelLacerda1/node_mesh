import time
from flask import Blueprint, render_template, jsonify, request, current_app
from flask_login import login_required, current_user
from app.services.ansible_service import AnsibleService
from app.services.audit_service import AuditService
from app.config import Config
from app.models.user import User 
from app.models.node import Node
from app.services.discovery_service import DiscoveryService

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
@login_required
def index():
    # Cache busting para garantir que o script.js
    version_id = int(time.time())
    return render_template('index.html', 
                           webssh_url=Config.WEBSSH_URL, 
                           ver=version_id)

@main_bp.route('/api/status', methods=['GET', 'POST'])
@login_required
def status():
    """
    Rota UNIFICADA para verificar status.
    Fase 3B: Tabela nodes como única fonte de verdade.
    """
    try:
        # Fluxo obrigatório do Reverificar:
        # 1. Usuário clica em Reverificar -> POST
        # 2. Executa run_scan() -> faz ping sweep e ip neigh -> salva na tabela nodes
        if request.method == 'POST':
            DiscoveryService.run_scan()
            
        # Lê a tabela nodes (já com dados atualizados caso tenha sido um POST)
        nodes_db = Node.query.all()
        
        results = []
        for node in nodes_db:
            nome = node.label if node.label else f"Nó {node.ip.split('.')[-1]}"
            results.append({
                'nome': nome,
                'ip': node.ip,
                'online': node.is_online
            })
            
        # Ordenação numérica obrigatória pelo último octeto do IP
        results = sorted(results, key=lambda x: int(x['ip'].split('.')[-1]))
        
        return jsonify({'nodes': results})
    except Exception as e:
        return jsonify({'error': 'status_check_failed', 'details': str(e)}), 500

@main_bp.route('/api/command', methods=['POST'])
@login_required
def run_command():
    data = request.json
    command = data.get('command')
    nodes = data.get('nodes', [])
    
    if not command or not nodes:
        return jsonify({'error': 'Dados inválidos'}), 400
        
    AuditService.log_action(current_user.username, "RUN_COMMAND", f"CMD: {command} ON {nodes}")
    
    results = AnsibleService.run_command(nodes, command)
    return jsonify(results)

@main_bp.route('/api/verify_password', methods=['POST'])
@login_required
def verify_password():
    data = request.get_json()
    password = data.get('password')

    if not password:
        return jsonify({'valid': False}), 400

    if current_user.check_password(password):
        return jsonify({'valid': True})
    else:
        return jsonify({'valid': False})
