import os
import json
import subprocess
import threading
import logging
import shutil
import time
import ansible_runner
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from app.config import Config
from app.extensions import db
from app.models.package import PackageJob, PackageJobNode
from app.services.ansible_service import AnsibleService

logger = logging.getLogger(__name__)


class PackageService:
    """
    Serviço de instalação remota de pacotes nos nós da rede mesh.
    
    Fluxo: validar pacote → validar nós → resolver deps → download → distribuir → instalar
    
    Restrições:
        - Somente a VM baixa pacotes (nós são offline)
        - Cache local persistente em data/packages/
        - Lock contra jobs simultâneos
        - Pré-validação de arquitetura e OS em cada nó
    """
    
    _install_lock = threading.Lock()
    _current_job_id = None
    
    # Catálogo de pacotes externos (fora dos repositórios Debian oficiais).
    # Adicionar novo pacote = nova entrada aqui. Nenhum método novo necessário.
    #
    # Campos obrigatórios:
    #   type            — tipo do artefato: 'deb' | (futuro: 'tgz', ...)
    #   download_method — mecanismo de download no Gateway: 'apt' | (futuro: 'url', ...)
    #   install_method  — mecanismo de instalação nos TV Box: 'dpkg' | (futuro: 'binary', ...)
    #   apt_package     — nome do pacote para apt-cache/apt-get download
    #
    # Campos opcionais (repositório APT adicional):
    #   apt_repo_key_url — URL da chave GPG do repositório
    #   apt_repo_key_id  — identificador do arquivo no keyring (/usr/share/keyrings/)
    #   apt_repo_line    — linha do sources.list
    #   Ausentes = pacote disponível nos repositórios padrão do Gateway.
    EXTERNAL_PACKAGES = {
        'tailscale': {
            'type': 'deb',
            'download_method': 'apt',
            'install_method': 'dpkg',
            'apt_package': 'tailscale',
            'apt_repo_key_url': 'https://pkgs.tailscale.com/stable/debian/bullseye.gpg',
            'apt_repo_key_id':  'tailscale-archive-keyring',
            'apt_repo_line':    'deb https://pkgs.tailscale.com/stable/debian bullseye main',
            'description': 'VPN mesh — pacote .deb para Debian bullseye/arm64',
        }
    }
    
    # Arquitetura e OS esperados nos nós
    EXPECTED_ARCH = 'arm64'
    EXPECTED_CODENAME = 'bullseye'
    
    # ===================================================================
    #  MÉTODOS PÚBLICOS
    # ===================================================================
    
    @classmethod
    def validate_package(cls, package_name: str) -> dict:
        """
        Verifica se um pacote existe nos repositórios Debian arm64
        ou no catálogo de pacotes externos.
        Não instala nada.
        """
        package_name = package_name.strip().lower()
        
        # 1. Verificar repositórios Debian arm64
        try:
            cmd = ['apt-cache', 'show', f'{package_name}:arm64']
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                version = None
                description = None
                for line in result.stdout.split('\n'):
                    if line.startswith('Version:') and not version:
                        version = line.split(':', 1)[1].strip()
                    if line.startswith('Description:') and not description:
                        description = line.split(':', 1)[1].strip()
                return {
                    'exists': True,
                    'type': 'debian',
                    'name': package_name,
                    'version': version,
                    'description': description,
                }
        except subprocess.TimeoutExpired:
            logger.warning(f"[PACKAGES] Timeout ao verificar pacote {package_name}")
        except Exception as e:
            logger.error(f"[PACKAGES] Erro ao verificar pacote: {e}")
        
        # 2. Verificar catálogo externo
        if package_name in cls.EXTERNAL_PACKAGES:
            info = cls.EXTERNAL_PACKAGES[package_name]
            return {
                'exists': True,
                'type': 'external',
                'name': package_name,
                'description': info.get('description', ''),
            }
        
        return {'exists': False, 'name': package_name}
    
    @classmethod
    def install_package(cls, package_name: str, node_ips: List[str],
                        requested_by: str, app) -> dict:
        """
        Ponto de entrada para instalação de pacote.
        Cria job, dispara thread de background, retorna job_id.
        Retorna imediatamente (202 Accepted pattern).
        """
        # Guard: lock contra jobs simultâneos
        if not cls._install_lock.acquire(blocking=False):
            return {
                'success': False,
                'error': 'job_in_progress',
                'current_job_id': cls._current_job_id,
                'message': 'Já existe um job de instalação em andamento.',
            }
        
        try:
            package_name = package_name.strip().lower()
            
            # Criar job no banco
            job = PackageJob(
                package_name=package_name,
                requested_by=requested_by,
                status='resolving',
                total_nodes=len(node_ips),
            )
            db.session.add(job)
            db.session.flush()
            
            # Criar entries por nó
            for ip in node_ips:
                node_entry = PackageJobNode(
                    job_id=job.id,
                    node_ip=ip,
                    status='pending',
                )
                db.session.add(node_entry)
            
            db.session.commit()
            cls._current_job_id = job.id
            
            logger.info(f"[PACKAGES] Job {job.id} criado: {package_name} para {len(node_ips)} nós")
            
            # Disparar thread de background
            thread = threading.Thread(
                target=cls._background_install,
                args=(app._get_current_object(), job.id, package_name, node_ips),
                name=f'pkg-install-{job.id}',
                daemon=True,
            )
            thread.start()
            
            return {
                'success': True,
                'job_id': job.id,
                'message': f'Job {job.id} iniciado para {package_name}',
            }
        
        except Exception as e:
            cls._install_lock.release()
            logger.error(f"[PACKAGES] Erro ao criar job: {e}")
            db.session.rollback()
            return {
                'success': False,
                'error': 'job_creation_failed',
                'message': str(e),
            }
    
    @classmethod
    def get_job(cls, job_id: int) -> Optional[dict]:
        """Retorna detalhes de um job com status de cada nó."""
        job = PackageJob.query.get(job_id)
        if not job:
            return None
        return job.to_dict_detail()
    
    @classmethod
    def get_jobs(cls, limit: int = 20, offset: int = 0) -> dict:
        """Lista jobs com paginação, mais recentes primeiro."""
        total = PackageJob.query.count()
        jobs = PackageJob.query.order_by(PackageJob.created_at.desc()) \
                               .limit(limit).offset(offset).all()
        return {
            'jobs': [j.to_dict() for j in jobs],
            'total': total,
            'limit': limit,
            'offset': offset,
        }
    
    @classmethod
    def get_cached_packages(cls) -> dict:
        """Retorna informações sobre o cache de pacotes."""
        cls._ensure_cache_dir()
        manifest = cls._load_manifest()
        
        packages = manifest.get('packages', {})
        total_size = sum(pkg.get('size_bytes', 0) for pkg in packages.values())
        
        return {
            'total_packages': len(packages),
            'total_size_bytes': total_size,
            'total_size_mb': round(total_size / (1024 * 1024), 2) if total_size > 0 else 0,
            'packages': packages,
            'last_updated': manifest.get('last_updated'),
        }
    
    @classmethod
    def get_available_nodes(cls) -> list:
        """Retorna nós online disponíveis para instalação."""
        from app.models.node import Node
        nodes = Node.query.filter_by(is_online=True).all()
        result = []
        for node in nodes:
            nome = node.label if node.label else f"Nó {node.ip.split('.')[-1]}"
            result.append({
                'ip': node.ip,
                'nome': nome,
                'is_online': node.is_online,
            })
        return sorted(result, key=lambda x: int(x['ip'].split('.')[-1]))
    
    @classmethod
    def is_busy(cls) -> bool:
        """Retorna True se um job está em andamento."""
        return cls._current_job_id is not None
    
    # ===================================================================
    #  BACKGROUND INSTALL (Thread)
    # ===================================================================
    
    @classmethod
    def _background_install(cls, app, job_id: int, package_name: str, node_ips: List[str]):
        """Thread de background que executa o fluxo completo de instalação."""
        try:
            with app.app_context():
                cls._execute_install(job_id, package_name, node_ips)
        except Exception as e:
            logger.error(f"[PACKAGES] Erro fatal no job {job_id}: {e}", exc_info=True)
            try:
                with app.app_context():
                    cls._update_job(job_id, status='error', error_message=str(e))
            except Exception:
                pass
        finally:
            cls._current_job_id = None
            cls._install_lock.release()
            logger.info(f"[PACKAGES] Lock liberado (job {job_id})")
    
    @classmethod
    def _execute_install(cls, job_id: int, package_name: str, node_ips: List[str]):
        """Executa o fluxo completo de instalação dentro do app_context."""
        
        # --- Etapa 1: Validar pacote ---
        logger.info(f"[PACKAGES] Job {job_id}: Verificando pacote '{package_name}'...")
        pkg_info = cls.validate_package(package_name)
        
        if not pkg_info['exists']:
            cls._update_job(job_id,
                status='error',
                error_message=f"Pacote '{package_name}' não encontrado nos repositórios "
                              f"Debian arm64 nem no catálogo de pacotes externos."
            )
            return
        
        pkg_type = pkg_info['type']
        cls._update_job(job_id, package_type=pkg_type, version=pkg_info.get('version'))
        
        # --- Etapa 2: Validar nós (arquitetura + OS) ---
        logger.info(f"[PACKAGES] Job {job_id}: Validando {len(node_ips)} nós...")
        cls._update_job(job_id, status='validating')
        
        compatible_ips = cls._validate_nodes(job_id, node_ips)
        
        if not compatible_ips:
            cls._update_job(job_id,
                status='failed',
                error_message='Nenhum nó compatível encontrado (todos falharam na '
                              'validação de arquitetura/OS ou estão offline).',
                completed_at=datetime.utcnow(),
            )
            cls._finalize_job_counters(job_id)
            return
        
        logger.info(f"[PACKAGES] Job {job_id}: {len(compatible_ips)} nós compatíveis de {len(node_ips)}")
        
        # --- Etapa 3: Resolver dependências e baixar (somente Debian) ---
        if pkg_type == 'debian':
            deb_files = cls._handle_debian_package(job_id, package_name)
            if not deb_files:
                cls._finalize_job_counters(job_id)
                return
            
            # --- Etapa 4: Distribuir e instalar ---
            cls._distribute_and_install_debs(job_id, deb_files, compatible_ips)
        
        elif pkg_type == 'external':
            cls._handle_external_package(job_id, package_name, compatible_ips)
        
        # --- Etapa 5: Finalizar ---
        cls._finalize_job_counters(job_id)
        
        job = PackageJob.query.get(job_id)
        if job.success_nodes > 0 and job.failed_nodes == 0 and job.offline_nodes == 0:
            final_status = 'completed'
        elif job.success_nodes > 0:
            final_status = 'completed_partial'
        else:
            final_status = 'failed'
        
        cls._update_job(job_id, status=final_status, completed_at=datetime.utcnow())
        logger.info(f"[PACKAGES] Job {job_id}: Finalizado — {final_status} "
                    f"(S:{job.success_nodes} F:{job.failed_nodes} O:{job.offline_nodes} K:{job.skipped_nodes})")
    
    # ===================================================================
    #  VALIDAÇÃO DE NÓS
    # ===================================================================
    
    @classmethod
    def _validate_nodes(cls, job_id: int, node_ips: List[str]) -> List[str]:
        """
        Valida arquitetura e OS de cada nó via Ansible.
        Marca nós incompatíveis como 'skipped' com motivo.
        Retorna lista de IPs compatíveis.
        """
        validation_cmd = (
            'echo "ARCH=$(dpkg --print-architecture)" && '
            'echo "CODENAME=$(. /etc/os-release && echo $VERSION_CODENAME)" && '
            'echo "PRETTY=$(. /etc/os-release && echo $PRETTY_NAME)"'
        )
        
        hosts_list = [{'ip': ip} for ip in node_ips]
        temp_dir = AnsibleService._create_inventory(hosts_list, user='fitpath')

        try:
            r = ansible_runner.run(
                private_data_dir=temp_dir,
                inventory=os.path.join(temp_dir, 'inventory.yml'),
                host_pattern='all',
                module='ansible.builtin.shell',
                module_args=validation_cmd,
                extravars={
                    'ansible_ssh_private_key_file': Config.SSH_KEY_PATH,
                    'ansible_ssh_common_args': AnsibleService.gateway_ssh_common_args('-o ConnectTimeout=5'),
                },
                quiet=True,
            )
            
            # Coletar eventos do Ansible
            event_results = {}
            if hasattr(r, 'events'):
                for event in r.events:
                    data = event.get('event_data', {})
                    host = data.get('host')
                    if not host or host not in node_ips:
                        continue
                    
                    if event['event'] == 'runner_on_ok':
                        stdout = data.get('res', {}).get('stdout', '')
                        event_results[host] = {'ok': True, 'stdout': stdout}
                    elif event['event'] == 'runner_on_unreachable':
                        msg = data.get('res', {}).get('msg', 'Nó inacessível')
                        event_results[host] = {'ok': False, 'unreachable': True, 'msg': msg}
                    elif event['event'] == 'runner_on_failed':
                        msg = data.get('res', {}).get('msg', '') or data.get('res', {}).get('stderr', 'Erro')
                        event_results[host] = {'ok': False, 'msg': msg}
            
            # Processar resultados e atualizar banco
            compatible_ips = []
            
            for ip in node_ips:
                node_entry = PackageJobNode.query.filter_by(job_id=job_id, node_ip=ip).first()
                if not node_entry:
                    continue
                
                if ip not in event_results:
                    node_entry.status = 'offline'
                    node_entry.message = 'Nó não respondeu à validação'
                    node_entry.completed_at = datetime.utcnow()
                    continue
                
                result = event_results[ip]
                
                if not result['ok']:
                    node_entry.status = 'offline' if result.get('unreachable') else 'failed'
                    node_entry.message = f"Falha na validação: {result.get('msg', 'desconhecido')}"
                    node_entry.completed_at = datetime.utcnow()
                    continue
                
                # Parsear output de validação
                stdout = result['stdout']
                arch = None
                codename = None
                pretty = None
                
                for line in stdout.split('\n'):
                    line = line.strip()
                    if line.startswith('ARCH='):
                        arch = line.split('=', 1)[1].strip()
                    elif line.startswith('CODENAME='):
                        codename = line.split('=', 1)[1].strip()
                    elif line.startswith('PRETTY='):
                        pretty = line.split('=', 1)[1].strip()
                
                node_entry.node_arch = arch
                node_entry.node_os = pretty or codename
                
                # Verificar compatibilidade
                reasons = []
                if arch != cls.EXPECTED_ARCH:
                    reasons.append(f'Arquitetura incompatível: {arch} (esperado: {cls.EXPECTED_ARCH})')
                if codename != cls.EXPECTED_CODENAME:
                    reasons.append(f'OS incompatível: {codename} (esperado: {cls.EXPECTED_CODENAME})')
                
                if reasons:
                    node_entry.status = 'skipped'
                    node_entry.message = '; '.join(reasons)
                    node_entry.completed_at = datetime.utcnow()
                    logger.warning(f"[PACKAGES] Nó {ip} incompatível: {'; '.join(reasons)}")
                else:
                    # Nó compatível — continua pendente para instalação
                    compatible_ips.append(ip)
            
            db.session.commit()
            return compatible_ips
        
        except Exception as e:
            logger.error(f"[PACKAGES] Erro na validação de nós: {e}", exc_info=True)
            return []
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    # ===================================================================
    #  PACOTES DEBIAN (Nível 1)
    # ===================================================================
    
    @classmethod
    def _handle_debian_package(cls, job_id: int, package_name: str) -> Optional[List[str]]:
        """Resolve dependências e baixa pacotes Debian arm64. Retorna lista de paths dos .deb."""
        
        # Resolver dependências
        logger.info(f"[PACKAGES] Job {job_id}: Resolvendo dependências de '{package_name}:arm64'...")
        cls._update_job(job_id, status='resolving')
        
        try:
            dep_list = cls._resolve_dependencies(package_name)
            logger.info(f"[PACKAGES] Job {job_id}: {len(dep_list)} pacotes na árvore de dependências")
        except Exception as e:
            cls._update_job(job_id, status='error',
                          error_message=f'Falha ao resolver dependências: {e}')
            return None
        
        # Verificar cache
        cls._ensure_cache_dir()
        manifest = cls._load_manifest()
        cached_files = []
        missing_packages = []
        
        debian_dir = os.path.join(Config.PACKAGES_CACHE_DIR, 'debian')
        
        for pkg in dep_list:
            cache_key = f'{pkg}:arm64'
            if cache_key in manifest.get('packages', {}):
                cached_path = os.path.join(
                    Config.PACKAGES_CACHE_DIR,
                    manifest['packages'][cache_key]['filename']
                )
                if os.path.exists(cached_path):
                    cached_files.append(cached_path)
                    continue
            missing_packages.append(pkg)
        
        cache_hit = len(missing_packages) == 0
        cls._update_job(job_id, cache_hit=cache_hit)
        
        if missing_packages:
            logger.info(f"[PACKAGES] Job {job_id}: {len(cached_files)} em cache, "
                       f"{len(missing_packages)} para baixar")
            cls._update_job(job_id, status='downloading')
            
            downloaded = cls._download_debs(job_id, missing_packages, manifest)
            if downloaded is None:
                return None
            cached_files.extend(downloaded)
        else:
            logger.info(f"[PACKAGES] Job {job_id}: Todos os {len(dep_list)} pacotes já em cache ✓")
        
        if not cached_files:
            cls._update_job(job_id, status='error',
                          error_message='Nenhum .deb disponível para instalação.')
            return None
        
        # Calcular tamanho total
        total_size = sum(os.path.getsize(f) for f in cached_files if os.path.exists(f))
        cls._update_job(job_id, total_debs=len(cached_files), total_size_bytes=total_size)
        
        return cached_files
    
    @staticmethod
    def _resolve_dependencies(package_name: str) -> List[str]:
        """
        Resolve dependências recursivas para um pacote arm64 via apt-cache.
        Retorna lista de nomes de pacotes (sem duplicatas).
        """
        cmd = [
            'apt-cache', 'depends',
            '--recurse',
            '--no-recommends',
            '--no-suggests',
            '--no-conflicts',
            '--no-breaks',
            '--no-replaces',
            '--no-enhances',
            f'{package_name}:arm64'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            raise RuntimeError(f"apt-cache depends falhou: {result.stderr.strip()}")
        
        packages = set()
        for line in result.stdout.strip().split('\n'):
            # Nomes de pacotes NÃO são indentados
            if not line or line[0] in (' ', '\t'):
                continue
            pkg = line.strip()
            # Pular pacotes virtuais e operadores
            if '<' in pkg or '>' in pkg or '|' in pkg:
                continue
            # Pular prefixos de tipo (caso apareçam sem indentação)
            if ':' in pkg and any(pkg.startswith(p) for p in
                    ['Depends', 'PreDepends', 'Suggests', 'Recommends',
                     'Conflicts', 'Breaks', 'Replaces', 'Enhances']):
                continue
            # Remover sufixo :arm64 para normalizar
            clean_name = pkg.split(':')[0] if ':' in pkg else pkg
            if clean_name:
                packages.add(clean_name)
        
        if not packages:
            raise RuntimeError(f"Nenhuma dependência encontrada para {package_name}:arm64")
        
        return sorted(packages)
    
    @classmethod
    def _download_debs(cls, job_id: int, packages: List[str],
                       manifest: dict) -> Optional[List[str]]:
        """Baixa .deb arm64 faltantes para o cache local."""
        debian_dir = os.path.join(Config.PACKAGES_CACHE_DIR, 'debian')
        downloaded_files = []
        errors = []
        
        for i, pkg in enumerate(packages):
            try:
                logger.info(f"[PACKAGES] Job {job_id}: Baixando {pkg}:arm64 "
                           f"({i+1}/{len(packages)})...")
                
                cmd = ['apt-get', 'download', f'{pkg}:arm64']
                result = subprocess.run(
                    cmd, capture_output=True, text=True,
                    cwd=debian_dir, timeout=120
                )
                
                if result.returncode != 0:
                    stderr = result.stderr.strip()
                    # Pacotes virtuais/meta não podem ser baixados — pular
                    if any(msg in stderr for msg in [
                        'has no installation candidate',
                        'virtual package',
                        'is not a real package',
                        'has no versions',
                    ]):
                        logger.debug(f"[PACKAGES] Pacote virtual/meta {pkg} ignorado")
                        continue
                    errors.append(f"{pkg}: {stderr[:200]}")
                    logger.warning(f"[PACKAGES] Falha ao baixar {pkg}: {stderr[:200]}")
                    continue
                
                # Localizar o .deb baixado (nome_versão_arch.deb)
                deb_file = cls._find_downloaded_deb(debian_dir, pkg)
                
                if deb_file:
                    downloaded_files.append(deb_file)
                    
                    # Registrar no manifesto
                    filename = os.path.basename(deb_file)
                    manifest['packages'][f'{pkg}:arm64'] = {
                        'name': pkg,
                        'architecture': 'arm64',
                        'origin': 'debian',
                        'filename': f'debian/{filename}',
                        'size_bytes': os.path.getsize(deb_file),
                        'downloaded_at': datetime.utcnow().isoformat(),
                    }
                
            except subprocess.TimeoutExpired:
                errors.append(f"{pkg}: timeout")
                logger.error(f"[PACKAGES] Timeout ao baixar {pkg}")
            except Exception as e:
                errors.append(f"{pkg}: {str(e)}")
                logger.error(f"[PACKAGES] Erro ao baixar {pkg}: {e}")
        
        # Salvar manifesto atualizado
        cls._save_manifest(manifest)
        
        if errors and not downloaded_files:
            cls._update_job(job_id, status='error',
                          error_message=f"Falha ao baixar pacotes: {'; '.join(errors[:5])}")
            return None
        
        if errors:
            logger.warning(f"[PACKAGES] {len(errors)} erros não-bloqueantes: "
                          f"{'; '.join(errors[:3])}")
        
        return downloaded_files
    
    @staticmethod
    def _find_downloaded_deb(debian_dir: str, pkg_name: str) -> Optional[str]:
        """Localiza o .deb mais recente no diretório de cache para um pacote."""
        best_match = None
        best_mtime = 0
        
        for f in os.listdir(debian_dir):
            if not f.endswith('.deb'):
                continue
            # Nome do .deb: nome_versão_arch.deb
            # Verifica se o arquivo corresponde ao pacote
            if f.startswith(pkg_name + '_') or f.startswith(pkg_name.replace('.', '') + '_'):
                full_path = os.path.join(debian_dir, f)
                mtime = os.path.getmtime(full_path)
                if mtime > best_mtime:
                    best_mtime = mtime
                    best_match = full_path
        
        return best_match
    
    # ===================================================================
    #  DISTRIBUIÇÃO E INSTALAÇÃO (Ansible)
    # ===================================================================
    
    @classmethod
    def _distribute_and_install_debs(cls, job_id: int, deb_files: List[str],
                                     node_ips: List[str]):
        """Distribui e instala .deb nos nós via Ansible."""
        logger.info(f"[PACKAGES] Job {job_id}: Distribuindo {len(deb_files)} .deb "
                    f"para {len(node_ips)} nós...")
        
        cls._update_job(job_id, status='installing')
        
        # Marcar nós como 'installing'
        for ip in node_ips:
            node_entry = PackageJobNode.query.filter_by(job_id=job_id, node_ip=ip).first()
            if node_entry and node_entry.status == 'pending':
                node_entry.status = 'installing'
                node_entry.started_at = datetime.utcnow()
        db.session.commit()
        
        hosts_list = [{'ip': ip} for ip in node_ips]
        temp_dir = AnsibleService._create_inventory(hosts_list, user='fitpath')

        try:
            # Staging: copiar .deb para diretório temporário
            debs_staging = os.path.join(temp_dir, 'debs')
            os.makedirs(debs_staging)
            for deb_path in deb_files:
                if os.path.exists(deb_path):
                    shutil.copy2(deb_path, debs_staging)

            # Lista de .deb para o playbook
            deb_file_list = [
                os.path.join(debs_staging, f)
                for f in sorted(os.listdir(debs_staging))
                if f.endswith('.deb')
            ]
            
            playbook_path = os.path.join(Config.ANSIBLE_DIR, 'playbooks', 'install_package.yml')
            
            extravars = {
                'deb_files': deb_file_list,
                'ansible_ssh_private_key_file': Config.SSH_KEY_PATH,
                'ansible_ssh_common_args': AnsibleService.gateway_ssh_common_args('-o ConnectTimeout=10'),
                'ansible_become': True,
                'ansible_become_password': Config.ANSIBLE_BECOME_PASSWORD,
            }
            
            r = ansible_runner.run(
                private_data_dir=temp_dir,
                inventory=os.path.join(temp_dir, 'inventory.yml'),
                playbook=playbook_path,
                extravars=extravars,
                quiet=True,
            )
            
            # Processar resultados por nó
            cls._process_ansible_results(job_id, r, node_ips)
            
            logger.info(f"[PACKAGES] Job {job_id}: Ansible finalizado (rc={r.rc})")
        
        except Exception as e:
            logger.error(f"[PACKAGES] Job {job_id}: Erro na distribuição: {e}", exc_info=True)
            for ip in node_ips:
                node_entry = PackageJobNode.query.filter_by(job_id=job_id, node_ip=ip).first()
                if node_entry and node_entry.status == 'installing':
                    node_entry.status = 'failed'
                    node_entry.message = f'Erro na distribuição: {str(e)[:300]}'
                    node_entry.completed_at = datetime.utcnow()
            db.session.commit()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    @classmethod
    def _process_ansible_results(cls, job_id: int, runner_result, node_ips: List[str]):
        """Processa eventos do Ansible e atualiza status por nó."""
        host_results = {}
        
        if hasattr(runner_result, 'events'):
            for event in runner_result.events:
                data = event.get('event_data', {})
                host = data.get('host')
                task = data.get('task', '')
                
                if not host or host not in node_ips:
                    continue
                
                if event['event'] == 'runner_on_ok':
                    # Só marcar sucesso na task de instalação (dpkg)
                    if 'dpkg' in task.lower() or 'instalar' in task.lower():
                        host_results[host] = {
                            'success': True,
                            'stdout': data.get('res', {}).get('stdout', ''),
                        }
                elif event['event'] == 'runner_on_failed':
                    host_results[host] = {
                        'success': False,
                        'msg': (data.get('res', {}).get('msg', '') or
                               data.get('res', {}).get('stderr', 'Erro desconhecido')),
                    }
                elif event['event'] == 'runner_on_unreachable':
                    host_results[host] = {
                        'success': False,
                        'unreachable': True,
                        'msg': data.get('res', {}).get('msg', 'Nó inacessível'),
                    }
        
        # Atualizar status no banco
        for ip in node_ips:
            node_entry = PackageJobNode.query.filter_by(job_id=job_id, node_ip=ip).first()
            if not node_entry:
                continue
            
            if ip in host_results:
                result = host_results[ip]
                if result.get('unreachable'):
                    node_entry.status = 'offline'
                    node_entry.message = result.get('msg', 'Nó inacessível durante instalação')
                elif result['success']:
                    node_entry.status = 'success'
                    stdout = result.get('stdout', '')
                    if stdout:
                        node_entry.message = stdout[:500]
                else:
                    node_entry.status = 'failed'
                    node_entry.message = result.get('msg', 'Erro na instalação')[:500]
            else:
                node_entry.status = 'offline'
                node_entry.message = 'Sem resposta do Ansible'
            
            node_entry.completed_at = datetime.utcnow()
        
        db.session.commit()
    
    # ===================================================================
    #  PACOTES EXTERNOS — download via Gateway + instalação via dpkg
    # ===================================================================

    @classmethod
    def _handle_external_package(cls, job_id: int, package_name: str,
                                 compatible_ips: List[str]):
        """
        Lida com pacotes do catálogo externo de forma genérica.
        O comportamento é inteiramente dirigido pelos campos do catálogo
        EXTERNAL_PACKAGES — nenhuma lógica específica por pacote.

        Fluxo:
          1. Verifica cache permanente da VM (manifesto).
          2. Cache miss → solicita download ao Gateway (ARM64 nativo).
          3. Despacha instalação pelo install_method do catálogo.
        """
        if package_name not in cls.EXTERNAL_PACKAGES:
            cls._update_job(job_id, status='error',
                            error_message=f'Pacote externo "{package_name}" não encontrado no catálogo.')
            return

        info = cls.EXTERNAL_PACKAGES[package_name]

        # --- Verificar cache permanente ---
        manifest = cls._load_manifest()
        ext_entry = manifest.get('external_packages', {}).get(package_name)
        deb_paths = []
        cache_hit = False

        if ext_entry:
            dest_dir = os.path.join(Config.PACKAGES_CACHE_DIR, 'external', package_name)
            candidate_paths = [
                os.path.join(dest_dir, f)
                for f in ext_entry.get('files', [])
            ]
            if candidate_paths and all(
                os.path.exists(p) and os.path.getsize(p) > 0
                for p in candidate_paths
            ):
                deb_paths = candidate_paths
                cache_hit = True
                logger.info(f"[PACKAGES] Job {job_id}: Cache hit para '{package_name}' "
                            f"({len(deb_paths)} .deb)")

        cls._update_job(job_id, cache_hit=cache_hit)

        if not cache_hit:
            cls._update_job(job_id, status='downloading')
            deb_paths = cls._download_external_package(job_id, package_name, info)
            if not deb_paths:
                cls._update_job(job_id, status='error',
                                error_message=f'Falha ao baixar "{package_name}" via Gateway.')
                return

        total_size = sum(os.path.getsize(f) for f in deb_paths if os.path.exists(f))
        cls._update_job(job_id, total_debs=len(deb_paths), total_size_bytes=total_size)

        # --- Despachar instalação pelo catálogo ---
        install_method = info.get('install_method', 'dpkg')
        if install_method == 'dpkg':
            cls._distribute_and_install_debs(job_id, deb_paths, compatible_ips)
        else:
            cls._update_job(job_id, status='error',
                            error_message=f'install_method "{install_method}" não implementado.')

    @classmethod
    def _download_external_package(cls, job_id: int, package_name: str,
                                   info: dict) -> Optional[List[str]]:
        """
        Ponto de entrada para download de qualquer pacote externo.
        Despacha pelo campo download_method do catálogo.
        Retorna lista de paths locais (cache permanente da VM) ou None.
        """
        download_method = info.get('download_method')

        if download_method == 'apt':
            return cls._download_via_apt_on_gateway(job_id, package_name, info)

        logger.error(f"[PACKAGES] Job {job_id}: download_method '{download_method}' "
                     f"não implementado para '{package_name}'")
        return None

    @classmethod
    def _download_via_apt_on_gateway(cls, job_id: int, package_name: str,
                                     info: dict) -> Optional[List[str]]:
        """
        Executa o download de pacotes ARM64 no Gateway via APT.

        O Gateway (ARM64 nativo) resolve dependências via apt-cache e baixa
        cada .deb via apt-get download, sem nenhuma instalação local.
        Os arquivos são copiados para o cache permanente da VM via Ansible fetch
        e removidos imediatamente do Gateway.

        Segue o mesmo padrão de _validate_nodes() e _distribute_and_install_debs():
        _create_inventory → ansible_runner.run → walk r.events → finally rmtree.
        """
        dest_dir = os.path.join(Config.PACKAGES_CACHE_DIR, 'external', package_name)
        os.makedirs(dest_dir, exist_ok=True)

        hosts_list = [{'ip': Config.DISCOVERY_GATEWAY_IP}]
        temp_dir = AnsibleService._create_inventory(hosts_list, user='fitpath')

        try:
            playbook_path = os.path.join(
                Config.ANSIBLE_DIR, 'playbooks', 'download_on_gateway.yml'
            )

            extravars = {
                'apt_package': info['apt_package'],
                'tmp_dir': f'/tmp/pkg_{job_id}',
                'dest_dir': dest_dir,
                'ansible_ssh_private_key_file': Config.SSH_KEY_PATH,
                'ansible_ssh_common_args': AnsibleService.gateway_direct_ssh_args(),
                'ansible_become_password': Config.ANSIBLE_BECOME_PASSWORD,
            }

            # Campos opcionais de configuração de repositório
            for field in ('apt_repo_key_url', 'apt_repo_key_id', 'apt_repo_line'):
                if field in info:
                    extravars[field] = info[field]

            logger.info(f"[PACKAGES] Job {job_id}: Solicitando download de "
                        f"'{package_name}' ao Gateway ({Config.DISCOVERY_GATEWAY_IP})...")

            r = ansible_runner.run(
                private_data_dir=temp_dir,
                inventory=os.path.join(temp_dir, 'inventory.yml'),
                playbook=playbook_path,
                extravars=extravars,
                quiet=True,
            )

            if r.rc != 0:
                logger.error(f"[PACKAGES] Job {job_id}: Playbook de download falhou (rc={r.rc})")
                if hasattr(r, 'events'):
                    for event in r.events:
                        if event['event'] in ('runner_on_failed', 'runner_on_unreachable'):
                            msg = (event.get('event_data', {})
                                       .get('res', {})
                                       .get('msg', ''))
                            if msg:
                                logger.error(f"[PACKAGES] Job {job_id}: Gateway: {msg}")
                return None

            # Listar .deb copiados para o cache permanente da VM
            deb_files = sorted([
                os.path.join(dest_dir, f)
                for f in os.listdir(dest_dir)
                if f.endswith('.deb') and os.path.isfile(os.path.join(dest_dir, f))
            ])

            if not deb_files:
                logger.error(f"[PACKAGES] Job {job_id}: Nenhum .deb em {dest_dir} "
                             f"após download no Gateway")
                return None

            # Registrar no manifesto (cache permanente — sem TTL, sem expiração)
            manifest = cls._load_manifest()
            if 'external_packages' not in manifest:
                manifest['external_packages'] = {}

            total_size = sum(os.path.getsize(f) for f in deb_files)
            manifest['external_packages'][package_name] = {
                'files': [os.path.basename(f) for f in deb_files],
                'total_size_bytes': total_size,
                'downloaded_at': datetime.utcnow().isoformat(),
                'origin': 'external',
                'package_type': info.get('type', 'deb'),
                'download_method': info.get('download_method', 'apt'),
                'install_method': info.get('install_method', 'dpkg'),
            }
            cls._save_manifest(manifest)

            logger.info(f"[PACKAGES] Job {job_id}: {len(deb_files)} .deb armazenados "
                        f"em cache permanente ({total_size // 1024} KB)")
            return deb_files

        except Exception as e:
            logger.error(f"[PACKAGES] Job {job_id}: Erro no download via Gateway: {e}",
                         exc_info=True)
            return None
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    # ===================================================================
    #  UTILITÁRIOS INTERNOS
    # ===================================================================
    
    @staticmethod
    def _ensure_cache_dir():
        """Garante que os diretórios de cache existem."""
        cache_dir = Config.PACKAGES_CACHE_DIR
        for subdir in ['debian', 'external']:
            path = os.path.join(cache_dir, subdir)
            if not os.path.exists(path):
                os.makedirs(path)
    
    @staticmethod
    def _load_manifest() -> dict:
        """Carrega o manifesto do cache."""
        manifest_path = os.path.join(Config.PACKAGES_CACHE_DIR, 'cache_manifest.json')
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                logger.warning("[PACKAGES] Manifesto corrompido, recriando...")
        return {'version': 1, 'last_updated': None, 'packages': {}}
    
    @staticmethod
    def _save_manifest(manifest: dict):
        """Salva o manifesto do cache de forma atômica."""
        manifest_path = os.path.join(Config.PACKAGES_CACHE_DIR, 'cache_manifest.json')
        tmp_path = manifest_path + '.tmp'
        manifest['last_updated'] = datetime.utcnow().isoformat()
        with open(tmp_path, 'w') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, manifest_path)
    
    @classmethod
    def _update_job(cls, job_id: int, **kwargs):
        """Atualiza campos do job no banco."""
        try:
            job = PackageJob.query.get(job_id)
            if job:
                for key, value in kwargs.items():
                    if hasattr(job, key):
                        setattr(job, key, value)
                db.session.commit()
        except Exception as e:
            logger.error(f"[PACKAGES] Erro ao atualizar job {job_id}: {e}")
            db.session.rollback()
    
    @classmethod
    def _finalize_job_counters(cls, job_id: int):
        """Calcula contadores finais do job com base nos status dos nós."""
        try:
            job = PackageJob.query.get(job_id)
            if not job:
                return
            
            nodes = PackageJobNode.query.filter_by(job_id=job_id).all()
            job.success_nodes = sum(1 for n in nodes if n.status == 'success')
            job.failed_nodes = sum(1 for n in nodes if n.status == 'failed')
            job.offline_nodes = sum(1 for n in nodes if n.status == 'offline')
            job.skipped_nodes = sum(1 for n in nodes if n.status == 'skipped')
            db.session.commit()
        except Exception as e:
            logger.error(f"[PACKAGES] Erro ao finalizar contadores: {e}")
            db.session.rollback()
