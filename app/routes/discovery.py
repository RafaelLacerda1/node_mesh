from flask import Blueprint, jsonify, render_template
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


# --- FASE 3A: Novas rotas ---

@discovery_bp.route('/api/discovery/scheduler', methods=['GET'])
@login_required
@admin_required
def scheduler_status():
    """
    Retorna informacoes do scheduler de scan automatico.
    Inclui: running, scan_count, last_scan_time, last_scan_result.
    """
    from app.services.scheduler import DiscoveryScheduler
    return jsonify(DiscoveryScheduler.get_status())


@discovery_bp.route('/discovery')
@login_required
@admin_required
def discovery_dashboard():
    """
    Tela administrativa de descoberta de nos.
    Exibe: lista de nos descobertos, status do scheduler,
    botao de scan manual, informacoes online/offline.
    """
    return render_template('discovery.html',
                           discovery_enabled=Config.DISCOVERY_ENABLED,
                           gateway_ip=Config.DISCOVERY_GATEWAY_IP,
                           interface=Config.DISCOVERY_INTERFACE,
                           interval=Config.DISCOVERY_INTERVAL_SECONDS,
                           threshold=Config.DISCOVERY_OFFLINE_THRESHOLD)
