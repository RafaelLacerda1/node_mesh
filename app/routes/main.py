import time
from flask import Blueprint, render_template, jsonify, request, current_app
from flask_login import login_required, current_user
from app.services.ansible_service import AnsibleService
from app.services.audit_service import AuditService
from app.config import Config
from app.models.user import User 

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
    Aceita GET (load inicial) e POST (refresh forçado).
    """
    # Gera IPs de 10.2.0.1 a 10.2.0.20
    nodes = [f"10.2.0.{i}" for i in range(1, 21)]
    
    try:
        results = AnsibleService.check_nodes_status(nodes)
        return jsonify({'nodes': results})
    except Exception as e:
        return jsonify({'error': 'ansible_execution_failed', 'details': str(e)}), 500

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
