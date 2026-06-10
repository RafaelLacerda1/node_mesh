from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models.user import User
from app.services.ansible_service import AnsibleService
from app.services.audit_service import AuditService
from app.utils.decorators import admin_required

# Criação do Blueprint com prefixo '/admin'
admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

@admin_bp.route('/', methods=['GET', 'POST'])
@login_required
@admin_required
def dashboard():
    """
    Painel principal do administrador.
    Gerencia a criação de usuários e visualização de logs.
    """
    if request.method == 'POST':
        # Coleta dados do formulário
        username = request.form.get('username')
        password = request.form.get('password')
        is_admin = request.form.get('is_admin') == 'on'
        
        # Validação básica
        if not username or not password:
            flash('Usuário e senha são obrigatórios.', 'danger')
        elif User.query.filter_by(username=username).first():
            flash('Este nome de usuário já existe.', 'warning')
        else:
            try:
                # 1. Cria usuário no Banco de Dados Local (SQLite)
                new_user = User(username=username, is_admin=is_admin)
                new_user.set_password(password)
                db.session.add(new_user)
                db.session.commit()
                
                # 2. Cria usuário nos Nós (Via Ansible)
                ansible_result = AnsibleService.manage_node_user(username, 'present', password)
                
                if ansible_result.get('success', False):
                    flash(f'Usuário "{username}" salvo no banco. Ansible: {ansible_result["message"]}', 'success' if ansible_result.get('status') == 'success' else 'warning')
                    AuditService.log_action(current_user.username, "CREATE_USER", f"Created user: {username}")
                else:
                    flash(f'Usuário "{username}" salvo no banco, mas Ansible falhou: {ansible_result["message"]}', 'danger')
                    AuditService.log_action(current_user.username, "CREATE_USER_PARTIAL", f"Created DB only: {username}")

            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao criar usuário: {str(e)}', 'danger')

    # Carrega dados para renderizar a página
    users = User.query.all()
    log_users = AuditService.list_log_users()
    
    return render_template('admin.html', users=users, log_users=log_users)


@admin_bp.route('/delete/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    """
    Rota para deletar um usuário do banco e dos nós.
    """
    user = User.query.get_or_404(user_id)
    
    # Impede que o admin delete a si mesmo
    if user.id == current_user.id:
        flash("Você não pode deletar a si mesmo.", "danger")
        return redirect(url_for('admin.dashboard'))
    
    username = user.username
    
    try:
        # 1. Remove do Banco de Dados
        db.session.delete(user)
        db.session.commit()
        
        # 2. Remove dos Nós (Via Ansible)
        ansible_result = AnsibleService.manage_node_user(username, 'absent')
        
        if ansible_result.get('success', False):
            flash(f'Usuário "{username}" removido do banco. Ansible: {ansible_result["message"]}', 'success' if ansible_result.get('status') == 'success' else 'warning')
        else:
            flash(f'Usuário "{username}" removido do banco, mas Ansible falhou: {ansible_result["message"]}', 'danger')
            
        AuditService.log_action(current_user.username, "DELETE_USER", f"Deleted user: {username}")
        
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao deletar usuário: {str(e)}', 'danger')
        
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/logs/<username>')
@login_required
@admin_required
def view_log(username):
    """
    Rota para visualizar o arquivo de log específico de um usuário.
    """
    content = AuditService.get_logs(username)
    return render_template('view_log.html', username=username, log_content=content)


@admin_bp.route('/reset/<int:user_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def reset_password(user_id):
    """
    Rota para resetar a senha de um usuário e sincronizar com os nós.
    """
    user = User.query.get_or_404(user_id)
    
    if request.method == 'POST':
        new_pass = request.form.get('new_password')
        
        if not new_pass:
            flash('A nova senha não pode ser vazia.', 'danger')
        else:
            try:
                # 1. Atualiza no Banco de Dados
                user.set_password(new_pass)
                db.session.commit()
                
                # 2. Atualiza nos Nós (Recriar/Atualizar com 'present' atualiza a senha)
                ansible_result = AnsibleService.manage_node_user(user.username, 'present', new_pass)
                
                if ansible_result.get('success', False):
                    flash(f'Senha de "{user.username}" atualizada no banco. Ansible: {ansible_result["message"]}', 'success' if ansible_result.get('status') == 'success' else 'warning')
                    AuditService.log_action(current_user.username, "RESET_PASSWORD", f"Reset password for: {user.username}")
                else:
                    flash(f'Senha atualizada no banco, mas Ansible falhou: {ansible_result["message"]}', 'danger')
                
                return redirect(url_for('admin.dashboard'))
                
            except Exception as e:
                db.session.rollback()
                flash(f'Erro ao resetar senha: {str(e)}', 'danger')
        
    return render_template('reset_password.html', user=user)
