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
    def manage_node_user(username: str, state: str, password: str = None) -> Dict[str, Any]:
        """
        Gerencia usuários nos nós.
        """
        from app.models.node import Node
        
        online_nodes = Node.query.filter_by(is_online=True).all()
        online_ips = sorted([node.ip for node in online_nodes], key=lambda ip: int(ip.split('.')[-1]))

        if not online_ips:
            logger.warning("Nenhum nó online encontrado no banco. Atualização feita apenas no banco local.")
            return {
                "success": True,
                "status": "no_nodes",
                "message": "Operação realizada localmente. Nenhum nó online para aplicar o Ansible.",
                "counts": {"success": 0, "failed": 0, "unreachable": 0, "total": 0},
                "hosts": {"success": [], "failed": [], "unreachable": []}
            }

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
            
            success_hosts = set()
            failed_hosts = set()
            unreachable_hosts = set()
            
            if hasattr(r, 'events'):
                for event in r.events:
                    event_name = event.get('event')
                    event_data = event.get('event_data', {})
                    host = event_data.get('host')
                    
                    if not host:
                        continue
                        
                    if event_name == 'runner_on_ok':
                        success_hosts.add(host)
                    elif event_name == 'runner_on_failed':
                        failed_hosts.add(host)
                        logger.error(f"Falha no host {host}")
                    elif event_name == 'runner_on_unreachable':
                        unreachable_hosts.add(host)
                        logger.error(f"Host inalcançável {host}")

            # Remoção de falsos sucessos (se falhou em alguma task, não é sucesso)
            final_success = list(success_hosts - failed_hosts - unreachable_hosts)
            final_failed = list(failed_hosts)
            final_unreachable = list(unreachable_hosts)

            success_count = len(final_success)
            fail_count = len(final_failed)
            unreachable_count = len(final_unreachable)
            total_count = len(hosts_list)

            # Lógica de status e success booleano
            if success_count > 0 and fail_count == 0 and unreachable_count == 0:
                status = "success"
                is_success = True
            elif success_count > 0 and (fail_count > 0 or unreachable_count > 0):
                status = "partial"
                is_success = True
            else:
                status = "failed"
                is_success = False

            # Montar a mensagem amigável
            msg_parts = []
            if success_count > 0: msg_parts.append(f"{success_count} nós atualizados com sucesso")
            if fail_count > 0: msg_parts.append(f"{fail_count} nós falharam")
            if unreachable_count > 0: msg_parts.append(f"{unreachable_count} nós inacessíveis")
            
            final_message = ", ".join(msg_parts) if msg_parts else "Nenhum nó processado pelo Ansible."

            logger.info(f"Resumo Ansible: {final_message}")

            return {
                "success": is_success,
                "status": status,
                "message": final_message,
                "counts": {
                    "success": success_count,
                    "failed": fail_count,
                    "unreachable": unreachable_count,
                    "total": total_count
                },
                "hosts": {
                    "success": final_success,
                    "failed": final_failed,
                    "unreachable": final_unreachable
                }
            }

        except Exception as e:
            logger.error(f"Erro Python: {e}")
            return {
                "success": False,
                "status": "error",
                "message": f"Erro interno: {str(e)}",
                "counts": {"success": 0, "failed": 0, "unreachable": 0, "total": len(hosts_list)},
                "hosts": {"success": [], "failed": [], "unreachable": []}
            }
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
