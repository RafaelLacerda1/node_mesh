import os
import yaml
import tempfile
import shutil
import ansible_runner
import logging
from typing import List, Dict, Any
from app.config import Config

logger = logging.getLogger(__name__)

class AnsibleService:
    @staticmethod
    def _create_inventory(hosts: List[Dict[str, str]], user: str) -> str:
        temp_dir = tempfile.mkdtemp(prefix='ansible_run_')
        inventory = {'all': {'hosts': {}}}
        
        for host in hosts:
            inventory['all']['hosts'][host['ip']] = {
                'ansible_user': user,
                'ansible_python_interpreter': '/usr/bin/python3'
            }
            
        with open(os.path.join(temp_dir, 'inventory.yml'), 'w') as f:
            yaml.dump(inventory, f)
        return temp_dir

    @staticmethod
    def check_nodes_status(nodes_ips: List[str]) -> List[Dict[str, Any]]:
        hosts_list = [{'ip': ip, 'nome': f"Nó {ip.split('.')[-1]}"} for ip in nodes_ips]
        temp_dir = AnsibleService._create_inventory(hosts_list, user='fitpath')
        
        try:
            extravars = {
                'ansible_ssh_private_key_file': Config.SSH_KEY_PATH,
                'ansible_ssh_common_args': '-o StrictHostKeyChecking=no -o ConnectTimeout=3'
            }

            r = ansible_runner.run(
                private_data_dir=temp_dir,
                inventory=os.path.join(temp_dir, 'inventory.yml'),
                module='ansible.builtin.ping',
                host_pattern='all',
                extravars=extravars,
                quiet=True
            )
            
            successful_hosts = []
            if hasattr(r, 'events'):
                for event in r.events:
                    if event['event'] == 'runner_on_ok':
                        successful_hosts.append(event['event_data']['host'])

            results = []
            for host in hosts_list:
                results.append({
                    'nome': host['nome'],
                    'ip': host['ip'],
                    'online': host['ip'] in successful_hosts
                })
            
            return sorted(results, key=lambda x: int(x['ip'].split('.')[-1]))
            
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def run_command(nodes_ips: List[str], command: str) -> List[Dict]:
        hosts_list = [{'ip': ip} for ip in nodes_ips]
        temp_dir = AnsibleService._create_inventory(hosts_list, user='fitpath')
        results_map = {ip: {'ip': ip, 'success': False, 'stdout': '', 'stderr': 'Sem resposta'} for ip in nodes_ips}
        
        try:
            r = ansible_runner.run(
                private_data_dir=temp_dir,
                inventory=os.path.join(temp_dir, 'inventory.yml'),
                host_pattern='all',
                module='ansible.builtin.command',
                module_args=command,
                extravars={
                    'ansible_ssh_private_key_file': Config.SSH_KEY_PATH,
                    'ansible_ssh_common_args': '-o StrictHostKeyChecking=no',
                    'ansible_become': True,
                    'ansible_become_password': 'cefetmg'
                },
                quiet=True
            )
            
            if hasattr(r, 'events'):
                for event in r.events:
                    data = event.get('event_data', {})
                    host = data.get('host')
                    if not host or host not in results_map: continue
                    res = data.get('res', {})
                    
                    if event['event'] == 'runner_on_ok':
                        results_map[host].update({
                            'success': True,
                            'stdout': res.get('stdout', ''),
                            'stderr': res.get('stderr', ''),
                            'exit_code': res.get('rc', 0)
                        })
                    elif event['event'] in ['runner_on_failed', 'runner_on_unreachable']:
                        results_map[host].update({
                            'success': False,
                            'stdout': res.get('stdout', ''),
                            'stderr': res.get('msg', 'Erro'),
                            'exit_code': res.get('rc', 1)
                        })
            return list(results_map.values())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def manage_node_user(username: str, state: str, password: str = None) -> bool:
        """
        Gerencia usuários. Retorna True se pelo menos UM nó for atualizado.
        """
        # 1. Filtra Online
        all_ips = [f"10.2.0.{i}" for i in range(1, 21)]
        status_nodes = AnsibleService.check_nodes_status(all_ips)
        online_ips = [n['ip'] for n in status_nodes if n['online']]

        if not online_ips:
            logger.warning("Nenhum nó online. Atualização feita apenas no banco local.")
            return True

        # 2. Executa Ansible
        hosts_list = [{'ip': ip} for ip in online_ips]
        temp_dir = AnsibleService._create_inventory(hosts_list, user='fitpath')
        
        try:
            pub_key_content = ""
            if os.path.exists(Config.SSH_KEY_PATH + ".pub"):
                with open(Config.SSH_KEY_PATH + ".pub", 'r') as f:
                    pub_key_content = f.read().strip()

            extravars = {
                'target_user': username,
                'target_state': state,
                'ansible_ssh_private_key_file': Config.SSH_KEY_PATH,
                'ansible_ssh_common_args': '-o StrictHostKeyChecking=no',
                'management_pub_key': pub_key_content,
                'ansible_become': True,
                'ansible_become_password': 'cefetmg'
            }
            
            if password:
                extravars['target_pass'] = password

            playbook_path = os.path.join(Config.ANSIBLE_DIR, 'playbooks', 'run_manage_user.yml')
            
            logger.info(f"Iniciando Ansible para '{username}'...")
            
            r = ansible_runner.run(
                private_data_dir=temp_dir,
                inventory=os.path.join(temp_dir, 'inventory.yml'),
                playbook=playbook_path,
                extravars=extravars,
                quiet=True
            )
            
            # 3. VERIFICACAO DE SUCESSO PARCIAL
            success_count = 0
            fail_count = 0
            
            if hasattr(r, 'events'):
                for event in r.events:
                    if event['event'] == 'runner_on_ok':
                        success_count += 1
                    elif event['event'] == 'runner_on_failed':
                        fail_count += 1
                        # Log do erro especifico para debug
                        host = event.get('event_data', {}).get('host')
                        msg = event.get('event_data', {}).get('res', {}).get('msg')
                        logger.error(f"Falha no host {host}: {msg}")

            logger.info(f"Resumo Ansible: {success_count} sucessos, {fail_count} falhas.")

            # Se pelo menos 1 funcionou, retornamos True para a interface
            if success_count > 0:
                return True
            
            # Se falhou em todos
            if fail_count > 0 and success_count == 0:
                return False
                
            # Se nao teve eventos, assume sucesso se RC=0
            return r.rc == 0

        except Exception as e:
            logger.error(f"Erro Python: {e}")
            return False
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
