from app.extensions import db
from datetime import datetime


class Node(db.Model):
    """
    Representa um TV Box (nó) na rede Ad-Hoc.
    Armazena informações de inventário e status.
    Não interfere com a tabela 'users' existente.
    """
    __tablename__ = 'nodes'

    id = db.Column(db.Integer, primary_key=True)
    ip = db.Column(db.String(15), unique=True, nullable=False, index=True)
    mac = db.Column(db.String(17), unique=True, nullable=True)
    hostname = db.Column(db.String(100), nullable=True)
    label = db.Column(db.String(100), nullable=True)
    os_info = db.Column(db.String(200), nullable=True)
    is_online = db.Column(db.Boolean, default=False)
    is_managed = db.Column(db.Boolean, default=False)
    ssh_user = db.Column(db.String(50), default='fitpath')
    source = db.Column(db.String(20), default='manual')  # 'manual', 'discovered', 'static'
    first_seen = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime, nullable=True)
    last_status_check = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'ip': self.ip,
            'mac': self.mac,
            'hostname': self.hostname,
            'label': self.label,
            'is_online': self.is_online,
            'is_managed': self.is_managed,
            'source': self.source,
            'first_seen': self.first_seen.isoformat() if self.first_seen else None,
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
        }

    def __repr__(self):
        return f'<Node {self.ip} ({self.label})>'
