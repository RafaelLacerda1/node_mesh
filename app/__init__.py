import os
from flask import Flask
from app.config import Config
from app.extensions import db, bcrypt, login_manager
from app.models.user import User
from app.models.node import Node

def create_app(config_class=Config):
    """
    Factory Pattern: Cria e configura a instância da aplicação Flask.
    """
    # Define caminhos relativos corretos para templates e static
    app = Flask(__name__, 
                template_folder='../templates', 
                static_folder='../static')
    
    # Carrega configuracoes do config.py
    app.config.from_object(config_class)

    # Inicializa as extensoes com a app criada
    db.init_app(app)
    bcrypt.init_app(app)
    login_manager.init_app(app)

    # Configuracao do Flask-Login: Como carregar o usuario a partir do ID na sessao
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # --- REGISTRO DE BLUEPRINTS ---
    # Gracas ao seu arquivo app/routes/__init__.py, podemos importar assim:
    from app.routes import auth_bp, main_bp, admin_bp, discovery_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(discovery_bp)

    # --- INICIALIZACAO DO BANCO DE DADOS ---
    # Cria as tabelas e o admin inicial dentro do contexto da aplicacao
    with app.app_context():
        create_database(app)

    # --- FASE 3A: SCAN AUTOMATICO ---
    # Inicia o scheduler de descoberta se DISCOVERY_ENABLED=true.
    # Guard contra dupla execucao no debug mode do Flask (reloader).
    if app.config.get('DISCOVERY_ENABLED', False):
        if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
            from app.services.scheduler import DiscoveryScheduler
            DiscoveryScheduler.start(app)

    return app

def create_database(app):
    """
    Cria o banco de dados e o usuário admin padrão se não existirem.
    """
    # Garante que a pasta 'data' exista
    if not os.path.exists(app.config['DB_FOLDER']):
        os.makedirs(app.config['DB_FOLDER'])
    
    # Cria todas as tabelas definidas nos Models
    db.create_all()
    
    # Verifica se ja existe um admin
    if not User.query.filter_by(username='admin').first():
        print("--> [INIT] Criando usuário 'admin' padrão...")
        admin = User(username='admin', is_admin=True)
        admin.set_password('admin') # Senha padrao, mude no primeiro acesso!
        db.session.add(admin)
        db.session.commit()
        print("--> [INIT] Usuário admin criado com sucesso.")
