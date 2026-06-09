from flask import Blueprint, jsonify
from flask_login import login_required
from app.utils.decorators import admin_required
from app.services.discovery_service import DiscoveryService
from app.config import Config

discovery_bp = Blueprint('discovery', __name__)


@discovery_bp.route('/api/discovery/status', methods=['GET'])
@login_required
@admin_required
def discovery_status():
    """
    Retorna o estado da feature de descoberta.
    Inclui conectividade com o gateway se DISCOVERY_ENABLED=true.
    Nao executa nenhum scan, apenas verifica status.
    """
    status = {
        'enabled': Config.DISCOVERY_ENABLED,
        'gateway_ip': Config.DISCOVERY_GATEWAY_IP,
        'interface': Config.DISCOVERY_INTERFACE,
        'method': DiscoveryService.DISCOVERY_METHOD
    }
    if Config.DISCOVERY_ENABLED:
        status['gateway'] = DiscoveryService.check_gateway_connectivity()
    return jsonify(status)


@discovery_bp.route('/api/discovery/scan', methods=['POST'])
@login_required
@admin_required
def run_discovery_scan():
    """
    Executa descoberta via SSH no gateway.
    Requer admin + DISCOVERY_ENABLED=true.
    Operacao somente leitura: ping sweep + ip neigh.
    """
    result = DiscoveryService.run_scan()
    status_code = 200 if result['success'] else 503
    return jsonify(result), status_code


@discovery_bp.route('/api/discovery/nodes', methods=['GET'])
@login_required
@admin_required
def list_discovered_nodes():
    """
    Lista todos os nos registrados na tabela nodes.
    Leitura passiva do banco — nao executa scan.
    """
    nodes = DiscoveryService.get_discovered_nodes()
    return jsonify({'nodes': nodes, 'total': len(nodes)})
