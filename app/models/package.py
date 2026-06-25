from app.extensions import db
from datetime import datetime


class PackageJob(db.Model):
    """
    Representa um job de instalação de pacote.
    Cada solicitação de instalação cria um novo job.
    
    Status possíveis:
        resolving       - Resolvendo dependências
        validating      - Validando arquitetura/OS dos nós
        downloading     - Baixando .deb da Internet
        distributing    - Enviando .deb para os nós via Ansible
        installing      - Instalando nos nós
        completed       - Todos os nós com sucesso
        completed_partial - Alguns nós com sucesso, outros falharam
        failed          - Todos os nós falharam
        error           - Erro antes de chegar aos nós (resolução/download)
    """
    __tablename__ = 'package_jobs'

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    package_name = db.Column(db.String(100), nullable=False)
    package_type = db.Column(db.String(20), default='debian')  # 'debian' ou 'external'
    version = db.Column(db.String(50), nullable=True)
    requested_by = db.Column(db.String(80), nullable=False)
    status = db.Column(db.String(30), default='resolving')
    total_nodes = db.Column(db.Integer, default=0)
    success_nodes = db.Column(db.Integer, default=0)
    failed_nodes = db.Column(db.Integer, default=0)
    offline_nodes = db.Column(db.Integer, default=0)
    skipped_nodes = db.Column(db.Integer, default=0)  # Nós incompatíveis (arch/OS)
    error_message = db.Column(db.Text, nullable=True)
    cache_hit = db.Column(db.Boolean, default=False)
    total_debs = db.Column(db.Integer, default=0)
    total_size_bytes = db.Column(db.Integer, default=0)

    # Relacionamento
    nodes = db.relationship('PackageJobNode', backref='job', lazy=True,
                           cascade='all, delete-orphan',
                           order_by='PackageJobNode.node_ip')

    def to_dict(self):
        return {
            'id': self.id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'package_name': self.package_name,
            'package_type': self.package_type,
            'version': self.version,
            'requested_by': self.requested_by,
            'status': self.status,
            'total_nodes': self.total_nodes,
            'success_nodes': self.success_nodes,
            'failed_nodes': self.failed_nodes,
            'offline_nodes': self.offline_nodes,
            'skipped_nodes': self.skipped_nodes,
            'error_message': self.error_message,
            'cache_hit': self.cache_hit,
            'total_debs': self.total_debs,
            'total_size_bytes': self.total_size_bytes,
        }

    def to_dict_detail(self):
        """Retorna o job com detalhes de cada nó."""
        d = self.to_dict()
        d['nodes'] = [n.to_dict() for n in self.nodes]
        return d

    def __repr__(self):
        return f'<PackageJob {self.id} {self.package_name} ({self.status})>'


class PackageJobNode(db.Model):
    """
    Representa o status de instalação de um pacote em um nó específico.
    Inclui resultados da pré-validação (arquitetura e OS).
    
    Status possíveis:
        pending     - Aguardando processamento
        validating  - Validação de arquitetura/OS em andamento
        installing  - Instalação em andamento
        success     - Instalação concluída com sucesso
        failed      - Falha na instalação
        offline     - Nó inacessível
        skipped     - Nó incompatível (arquitetura ou OS incorretos)
    """
    __tablename__ = 'package_job_nodes'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('package_jobs.id'), nullable=False)
    node_ip = db.Column(db.String(15), nullable=False)
    status = db.Column(db.String(20), default='pending')
    message = db.Column(db.Text, nullable=True)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    node_arch = db.Column(db.String(20), nullable=True)    # Resultado de dpkg --print-architecture
    node_os = db.Column(db.String(100), nullable=True)     # Resultado de /etc/os-release

    def to_dict(self):
        return {
            'id': self.id,
            'job_id': self.job_id,
            'node_ip': self.node_ip,
            'status': self.status,
            'message': self.message,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'node_arch': self.node_arch,
            'node_os': self.node_os,
        }

    def __repr__(self):
        return f'<PackageJobNode {self.node_ip} ({self.status})>'
