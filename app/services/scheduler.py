import threading
import time
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class DiscoveryScheduler:
    """
    Scheduler de scan automatico para descoberta de dispositivos na rede mesh.

    Arquitetura:
        - Thread daemon singleton que executa DiscoveryService.run_scan()
          a cada DISCOVERY_INTERVAL_SECONDS (padrao: 300s = 5 min).
        - Inicia automaticamente com o Flask via create_app().
        - Tolerante a falhas: try/except com log, nunca crasha.
        - Protegido pela flag DISCOVERY_ENABLED (deve ser True para iniciar).

    Fase 3A: Scan automatico + atualizacao da tabela nodes.
    """

    _instance = None
    _thread = None
    _running = False
    _lock = threading.Lock()
    _last_scan_result = None
    _last_scan_time = None
    _scan_count = 0

    @classmethod
    def start(cls, app):
        """
        Inicia a thread de scan automatico.

        Parametros:
            app: Instancia do Flask (necessaria para app_context no banco).

        Seguranca:
            - Singleton: nunca cria mais de uma thread.
            - Thread daemon: morre automaticamente com o processo principal.
        """
        with cls._lock:
            if cls._running:
                logger.warning("[DISCOVERY] Scheduler ja esta rodando. Ignorando start().")
                return

            cls._running = True
            interval = app.config.get('DISCOVERY_INTERVAL_SECONDS', 300)
            threshold = app.config.get('DISCOVERY_OFFLINE_THRESHOLD', 3)

            cls._thread = threading.Thread(
                target=cls._scan_loop,
                args=(app, interval),
                name='discovery-scheduler',
                daemon=True
            )
            cls._thread.start()

            logger.info(
                f"[DISCOVERY] Scheduler iniciado "
                f"(intervalo={interval}s, threshold={threshold})"
            )

    @classmethod
    def stop(cls):
        """Para o scheduler (usado em testes ou shutdown)."""
        with cls._lock:
            cls._running = False
            logger.info("[DISCOVERY] Scheduler parado.")

    @classmethod
    def _scan_loop(cls, app, interval):
        """
        Loop principal do scheduler.

        Fluxo:
            1. Executa scan imediato na inicializacao
            2. Aguarda 'interval' segundos
            3. Repete indefinidamente

        Tolerancia a falhas:
            - Cada scan esta em try/except individual
            - Falhas sao logadas mas NUNCA param o loop
            - O loop so para quando cls._running = False
        """
        # Scan imediato na inicializacao
        logger.info("[DISCOVERY] Executando scan inicial...")
        cls._execute_scan(app)

        while cls._running:
            try:
                # Aguarda o intervalo (verificando _running a cada segundo)
                for _ in range(interval):
                    if not cls._running:
                        return
                    time.sleep(1)

                # Executa o scan
                cls._execute_scan(app)

            except Exception as e:
                logger.error(f"[DISCOVERY] Erro inesperado no loop do scheduler: {e}")
                # Espera 30s antes de tentar novamente apos erro critico
                time.sleep(30)

    @classmethod
    def _execute_scan(cls, app):
        """
        Executa um unico scan dentro do app_context do Flask.
        Atualiza o estado interno do scheduler.
        """
        try:
            logger.info("[DISCOVERY] Scan iniciado")
            scan_start = time.time()

            with app.app_context():
                from app.services.discovery_service import DiscoveryService
                result = DiscoveryService.run_scan()

            duration = round(time.time() - scan_start, 2)
            cls._scan_count += 1
            cls._last_scan_time = datetime.utcnow()
            cls._last_scan_result = result

            if result.get('success'):
                total = result.get('total_found', 0)
                logger.info(f"[DISCOVERY] {total} dispositivos encontrados")
                logger.info(f"[DISCOVERY] Scan concluido em {duration}s")
            else:
                error = result.get('error', 'unknown')
                logger.warning(f"[DISCOVERY] Scan falhou ({duration}s): {error}")

        except Exception as e:
            cls._last_scan_result = {'success': False, 'error': str(e)}
            cls._last_scan_time = datetime.utcnow()
            logger.error(f"[DISCOVERY] Erro ao executar scan: {e}")

    @classmethod
    def get_status(cls) -> dict:
        """
        Retorna informacoes do scheduler para a API.

        Retorno:
            - running: bool — se o scheduler esta ativo
            - scan_count: int — total de scans executados
            - last_scan_time: str — timestamp do ultimo scan
            - last_scan_result: dict — resultado do ultimo scan
        """
        return {
            'running': cls._running,
            'scan_count': cls._scan_count,
            'last_scan_time': cls._last_scan_time.isoformat() if cls._last_scan_time else None,
            'last_scan_result': cls._last_scan_result,
            'thread_alive': cls._thread.is_alive() if cls._thread else False
        }
