from functools import wraps
from flask import abort
from flask_login import current_user

def admin_required(f):
    """
    Decorator para restringir o acesso a rotas apenas para administradores.
    Se o usuário não estiver logado ou não for admin, retorna erro 403 (Forbidden).
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Verifica se esta autenticado e se a flag is_admin eh verdadeira
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403) # Retorna "Proibido"
        return f(*args, **kwargs)
    return decorated_function
