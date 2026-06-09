import subprocess
import logging
import re
import time
from datetime import datetime
from app.config import Config
from app.extensions import db
from app.models.node import Node

logger = logging.getLogger(__name__)


class DiscoveryService:
    """
    Servico de descoberta de dispositivos na rede Ad-Hoc.

    Arquitetura:
        VM (172.30.0.14) --SSH--> Gateway (172.30.0.13) --wlan0--> Rede 10.2.0.0/24

    Metodo: ping sweep + ip neigh (somente leitura, zero instalacao no gateway).
    Seguranca: Protegido pela flag DISCOVERY_ENABLED (false por padrao).
    Isolamento: Falhas aqui NUNCA afetam dashboard, Ansible, SSH ou autenticacao.
    """

    # --- TIMEOUTS EXPLICITOS ---
    SSH_CONNECT_TIMEOUT = 5     # segundos para estabelecer conexao SSH
    SSH_COMMAND_TIMEOUT = 60    # segundos para o comando completo (ping sweep + ip neigh)

    # Metodo utilizado na descoberta
    DISCOVERY_METHOD = 'ping_sweep+ip_neigh'

    # Comando executado no gateway (SOMENTE LEITURA):
    # 1. Ping sweep paralelo com timeout de 1s por host (popula tabela ARP)
    # 2. Leitura da tabela ARP via ip neigh (nao altera nada)
    _SCAN_COMMAND = (
        'for i in $(seq 1 254); do '
        'ping -c1 -W1 {subnet}.$i > /dev/null 2>&1 & '
        '[ $((i % 50)) -eq 0 ] && wait; '
        'done; wait; '
        'ip neigh show dev {interface} | grep -v FAILED'
    )

    @staticmethod
    def _build_ssh_command(remote_cmd: str) -> list:
        """
        Constroi o comando SSH para executar no gateway.
        Usa BatchMode=yes para nunca solicitar senha interativamente.
        """
        return [
            'ssh',
            '-o', 'StrictHostKeyChecking=no',
            '-o', f'ConnectTimeout={DiscoveryService.SSH_CONNECT_TIMEOUT}',
            '-o', 'BatchMode=yes',
            '-i', Config.SSH_KEY_PATH,
            f'fitpath@{Config.DISCOVERY_GATEWAY_IP}',
            remote_cmd
        ]

    @staticmethod
    def check_gateway_connectivity() -> dict:
        """
        Verifica se a VM consegue conectar via SSH ao gateway.
        Retorna status detalhado sem executar nenhum scan.
        """
        if not Config.DISCOVERY_ENABLED:
            return {
                'reachable': False,
                'reason': 'discovery_disabled',
                'gateway_ip': Config.DISCOVERY_GATEWAY_IP
            }

        try:
            cmd = DiscoveryService._build_ssh_command('echo ok')
            start = time.time()
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=DiscoveryService.SSH_CONNECT_TIMEOUT + 5
            )
            elapsed = round(time.time() - start, 2)

            reachable = result.returncode == 0
            reason = 'ok' if reachable else result.stderr.strip()

            if reachable:
                logger.info(f"Gateway {Config.DISCOVERY_GATEWAY_IP} acessivel ({elapsed}s)")
            else:
                logger.warning(f"Gateway {Config.DISCOVERY_GATEWAY_IP} inacessivel: {reason}")

            return {
                'reachable': reachable,
                'reason': reason,
                'gateway_ip': Config.DISCOVERY_GATEWAY_IP,
                'response_time_s': elapsed
            }
        except subprocess.TimeoutExpired:
            logger.error(f"Gateway {Config.DISCOVERY_GATEWAY_IP}: SSH timeout ({DiscoveryService.SSH_CONNECT_TIMEOUT}s)")
            return {
                'reachable': False,
                'reason': f'ssh_timeout ({DiscoveryService.SSH_CONNECT_TIMEOUT}s)',
                'gateway_ip': Config.DISCOVERY_GATEWAY_IP
            }
        except Exception as e:
            logger.error(f"Erro ao verificar gateway: {e}")
            return {
                'reachable': False,
                'reason': str(e),
                'gateway_ip': Config.DISCOVERY_GATEWAY_IP
            }

    @staticmethod
    def run_scan() -> dict:
        """
        Executa descoberta via SSH no gateway.

        Fluxo:
            1. Verifica se DISCOVERY_ENABLED=true
            2. Conecta via SSH ao gateway
            3. Executa ping sweep (popula tabela ARP)
            4. Le tabela ARP com ip neigh
            5. Parseia resultados
            6. Salva no banco de dados

        Retorna dict com informacoes detalhadas:
            - success: bool
            - devices: lista de dispositivos encontrados
            - total_found: quantidade de dispositivos
            - total_saved: quantidade salva/atualizada no banco
            - duration_s: duracao da execucao em segundos
            - method: metodo utilizado
            - gateway_reachable: se o gateway respondeu
            - error: codigo de erro (se houver)
            - message: mensagem legivel (se houver)
        """
        # --- GUARD: Feature desabilitada ---
        if not Config.DISCOVERY_ENABLED:
            logger.debug("Tentativa de scan com DISCOVERY_ENABLED=false. Ignorando.")
            return {
                'success': False,
                'error': 'discovery_disabled',
                'devices': [],
                'total_found': 0,
                'total_saved': 0,
                'duration_s': 0,
                'method': DiscoveryService.DISCOVERY_METHOD,
                'gateway_reachable': False,
                'message': 'Descoberta desabilitada. Defina DISCOVERY_ENABLED=true para ativar.'
            }

        scan_start = time.time()
        scan_time = datetime.utcnow()

        remote_cmd = DiscoveryService._SCAN_COMMAND.format(
            subnet=Config.NODE_SUBNET,
            interface=Config.DISCOVERY_INTERFACE
        )

        try:
            ssh_cmd = DiscoveryService._build_ssh_command(remote_cmd)
            logger.info(
                f"[DISCOVERY] Iniciando scan via gateway {Config.DISCOVERY_GATEWAY_IP} "
                f"(interface={Config.DISCOVERY_INTERFACE}, metodo={DiscoveryService.DISCOVERY_METHOD})"
            )

            result = subprocess.run(
                ssh_cmd, capture_output=True, text=True,
                timeout=DiscoveryService.SSH_COMMAND_TIMEOUT
            )

            duration = round(time.time() - scan_start, 2)

            # SSH falhou completamente (sem saida)
            if result.returncode != 0 and not result.stdout.strip():
                error_msg = result.stderr.strip() or 'Sem resposta do gateway'
                logger.error(f"[DISCOVERY] SSH falhou ({duration}s): {error_msg}")
                return {
                    'success': False,
                    'error': 'gateway_unreachable',
                    'devices': [],
                    'total_found': 0,
                    'total_saved': 0,
                    'duration_s': duration,
                    'method': DiscoveryService.DISCOVERY_METHOD,
                    'gateway_reachable': False,
                    'message': f'Gateway inacessivel: {error_msg}'
                }

            # Parsear resultados
            devices = DiscoveryService._parse_ip_neigh(result.stdout)
            saved_count = DiscoveryService._save_to_db(devices, scan_time)

            logger.info(
                f"[DISCOVERY] Concluido em {duration}s: "
                f"{len(devices)} encontrados, {saved_count} salvos/atualizados"
            )

            return {
                'success': True,
                'devices': devices,
                'total_found': len(devices),
                'total_saved': saved_count,
                'duration_s': duration,
                'method': DiscoveryService.DISCOVERY_METHOD,
                'gateway_reachable': True,
                'scan_time': scan_time.isoformat(),
                'gateway': Config.DISCOVERY_GATEWAY_IP,
                'interface': Config.DISCOVERY_INTERFACE
            }

        except subprocess.TimeoutExpired:
            duration = round(time.time() - scan_start, 2)
            logger.error(
                f"[DISCOVERY] Timeout apos {duration}s "
                f"(limite={DiscoveryService.SSH_COMMAND_TIMEOUT}s)"
            )
            return {
                'success': False,
                'error': 'scan_timeout',
                'devices': [],
                'total_found': 0,
                'total_saved': 0,
                'duration_s': duration,
                'method': DiscoveryService.DISCOVERY_METHOD,
                'gateway_reachable': True,  # conectou mas demorou
                'message': f'Scan excedeu o tempo limite ({DiscoveryService.SSH_COMMAND_TIMEOUT}s).'
            }
        except Exception as e:
            duration = round(time.time() - scan_start, 2)
            logger.error(f"[DISCOVERY] Erro inesperado apos {duration}s: {e}")
            return {
                'success': False,
                'error': 'unexpected_error',
                'devices': [],
                'total_found': 0,
                'total_saved': 0,
                'duration_s': duration,
                'method': DiscoveryService.DISCOVERY_METHOD,
                'gateway_reachable': False,
                'message': str(e)
            }

    @staticmethod
    def _parse_ip_neigh(output: str) -> list:
        """
        Parseia a saida do 'ip neigh show dev <interface>'.

        Formato esperado (uma linha por dispositivo):
            10.2.0.2 lladdr aa:bb:cc:dd:ee:ff REACHABLE
            10.2.0.3 lladdr 11:22:33:44:55:66 STALE

        Retorna lista de dicts: [{'ip': ..., 'mac': ..., 'state': ...}]
        """
        devices = []
        pattern = re.compile(
            r'^(\d+\.\d+\.\d+\.\d+)\s+'    # IP
            r'.*?lladdr\s+'                  # keyword lladdr
            r'([0-9a-fA-F:]{17})\s+'         # MAC address
            r'(\S+)'                          # STATE (REACHABLE, STALE, DELAY, etc)
        )
        for line in output.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            match = pattern.match(line)
            if match:
                devices.append({
                    'ip': match.group(1),
                    'mac': match.group(2).lower(),
                    'state': match.group(3)
                })
        return devices

    @staticmethod
    def _save_to_db(devices: list, scan_time: datetime) -> int:
        """
        Salva/atualiza dispositivos descobertos na tabela nodes.

        Regras (SOMENTE LEITURA no sentido de nao alterar dados criticos):
            - NUNCA remove nos existentes
            - NUNCA altera 'source' de nos manuais/estaticos
            - NUNCA altera 'is_managed', 'label', 'ssh_user', 'notes'
            - Preenche MAC vazio em nos manuais
            - Atualiza last_seen para todos os nos encontrados
            - Novos nos sao criados com source='discovered', is_managed=False

        Fase 3A — Logica de online/offline com tolerancia:
            - Nos encontrados: is_online=True, missed_scans=0
            - Nos NAO encontrados (source='discovered'):
              missed_scans += 1
              Se missed_scans >= DISCOVERY_OFFLINE_THRESHOLD (padrao 3): is_online=False

        Retorna quantidade de registros salvos/atualizados.
        """
        saved = 0
        found_ips = set()

        for dev in devices:
            try:
                found_ips.add(dev['ip'])
                node = Node.query.filter_by(ip=dev['ip']).first()

                if node:
                    # Marca como online e reseta contador
                    node.is_online = True
                    node.missed_scans = 0
                    node.last_seen = scan_time

                    if node.source == 'discovered':
                        # No descoberto previamente: atualiza MAC
                        node.mac = dev['mac']
                    elif not node.mac:
                        # No manual/estatico sem MAC: preenche MAC
                        node.mac = dev['mac']
                    # No manual/estatico com MAC: nao altera MAC
                else:
                    # Dispositivo novo: cria com source='discovered'
                    node = Node(
                        ip=dev['ip'],
                        mac=dev['mac'],
                        source='discovered',
                        first_seen=scan_time,
                        last_seen=scan_time,
                        is_online=True,
                        is_managed=False,
                        missed_scans=0
                    )
                    db.session.add(node)

                saved += 1
            except Exception as e:
                logger.error(f"[DISCOVERY] Erro ao salvar {dev['ip']}: {e}")
                continue

        # --- Fase 3A: Marcar nos NAO encontrados ---
        # Incrementa missed_scans para nos 'discovered' que nao apareceram neste scan.
        # So executa se houve dispositivos encontrados (gateway acessivel).
        # Se found_ips estiver vazio, NAO penaliza — pode ser falha do gateway.
        if found_ips:
            try:
                offline_threshold = Config.DISCOVERY_OFFLINE_THRESHOLD
                not_found_nodes = Node.query.filter(
                    Node.source == 'discovered',
                    Node.is_online == True,
                    ~Node.ip.in_(found_ips)
                ).all()

                for node in not_found_nodes:
                    node.missed_scans = (node.missed_scans or 0) + 1
                    if node.missed_scans >= offline_threshold:
                        node.is_online = False
                        logger.info(
                            f"[DISCOVERY] {node.ip} marcado OFFLINE "
                            f"(missed_scans={node.missed_scans}, threshold={offline_threshold})"
                        )
            except Exception as e:
                logger.error(f"[DISCOVERY] Erro ao processar nos offline: {e}")

        try:
            db.session.commit()
            logger.info(f"[DISCOVERY] {saved} registros commitados no banco")
        except Exception as e:
            logger.error(f"[DISCOVERY] Erro ao commitar: {e}")
            db.session.rollback()
            return 0

        return saved

    @staticmethod
    def get_discovered_nodes() -> list:
        """Retorna todos os nos da tabela nodes (leitura passiva)."""
        try:
            nodes = Node.query.order_by(Node.ip).all()
            return [n.to_dict() for n in nodes]
        except Exception as e:
            logger.error(f"[DISCOVERY] Erro ao consultar tabela nodes: {e}")
            return []

