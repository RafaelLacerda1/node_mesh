from flask import Blueprint, jsonify, request, render_template, current_app
from flask_login import login_required, current_user
from app.utils.decorators import admin_required
from app.services.package_service import PackageService
from app.services.audit_service import AuditService
from app.config import Config

packages_bp = Blueprint('packages', __name__)


@packages_bp.route('/packages')
@login_required
@admin_required
def packages_dashboard():
    """Página de instalação de pacotes."""
    return render_template('packages.html',
                           packages_enabled=Config.PACKAGES_ENABLED)


@packages_bp.route('/api/packages/install', methods=['POST'])
@login_required
@admin_required
def install_package():
    """
    Inicia instalação de pacote nos nós selecionados.
    Body: {package_name: str, nodes: [str]}
    Retorna: 202 {job_id} ou erro.
    """
    if not Config.PACKAGES_ENABLED:
        return jsonify({
            'success': False,
            'error': 'packages_disabled',
            'message': 'Instalação de pacotes desabilitada. Defina PACKAGES_ENABLED=true.',
        }), 403

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'invalid_request'}), 400

    package_name = data.get('package_name', '').strip()
    node_ips = data.get('nodes', [])

    if not package_name:
        return jsonify({'success': False, 'error': 'missing_package_name',
                       'message': 'Nome do pacote é obrigatório.'}), 400
    if not node_ips:
        return jsonify({'success': False, 'error': 'missing_nodes',
                       'message': 'Selecione pelo menos um nó.'}), 400

    # Auditoria
    AuditService.log_action(
        current_user.username,
        "INSTALL_PACKAGE",
        f"Pacote: {package_name} em {len(node_ips)} nós: {', '.join(node_ips)}"
    )

    result = PackageService.install_package(
        package_name=package_name,
        node_ips=node_ips,
        requested_by=current_user.username,
        app=current_app,
    )

    if result['success']:
        return jsonify(result), 202
    else:
        status_code = 409 if result.get('error') == 'job_in_progress' else 500
        return jsonify(result), status_code


@packages_bp.route('/api/packages/jobs', methods=['GET'])
@login_required
@admin_required
def list_jobs():
    """Lista jobs de instalação com paginação."""
    limit = request.args.get('limit', 20, type=int)
    offset = request.args.get('offset', 0, type=int)
    return jsonify(PackageService.get_jobs(limit=limit, offset=offset))


@packages_bp.route('/api/packages/jobs/<int:job_id>', methods=['GET'])
@login_required
@admin_required
def get_job(job_id):
    """Retorna detalhes de um job específico com status de cada nó."""
    job = PackageService.get_job(job_id)
    if not job:
        return jsonify({'error': 'job_not_found'}), 404
    return jsonify(job)


@packages_bp.route('/api/packages/validate', methods=['POST'])
@login_required
@admin_required
def validate_package():
    """Valida se um pacote existe nos repositórios (sem instalar)."""
    data = request.get_json()
    if not data or not data.get('package_name'):
        return jsonify({'error': 'missing_package_name'}), 400

    result = PackageService.validate_package(data['package_name'].strip())
    return jsonify(result)


@packages_bp.route('/api/packages/cache', methods=['GET'])
@login_required
@admin_required
def get_cache():
    """Retorna informações sobre o cache de pacotes."""
    return jsonify(PackageService.get_cached_packages())


@packages_bp.route('/api/packages/nodes', methods=['GET'])
@login_required
@admin_required
def get_available_nodes():
    """Retorna nós online disponíveis para instalação."""
    nodes = PackageService.get_available_nodes()
    return jsonify({'nodes': nodes, 'total': len(nodes)})
