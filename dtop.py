import argparse
import os
import paramiko

import xml.etree.ElementTree as ET

def load_ssh_config(path='~/.ssh/config'):
    config = paramiko.SSHConfig()
    config_file = os.path.expanduser(path)
    if os.path.exists(config_file):
        with open(config_file) as f:
            config.parse(f)
    return config

def connect_ssh(config, hostname, username):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    cfg = {'hostname': hostname, 'username': username}
    user_config = config.lookup(cfg['hostname'])
    for k in ('hostname', 'username', 'port'):
        if k in user_config:
            cfg[k] = user_config[k]
    #cfg['sock'] = user_config.get('proxycommand')
    client.connect(**cfg)
    return client

def get_cpu_usage(client):
    _, stdout, _ = client.exec_command('vmstat')
    value_line = stdout.readlines()[2]
    values = value_line.split()
    cpu_usage = 100 - int(values[14])

    _, stdout, _ = client.exec_command('free')
    free_result = stdout.readlines()
    mem_total = int(free_result[1].split()[1])
    mem_used  = int(free_result[2].split()[2])
    mem_usage = 100 * mem_used // mem_total

    return {'%cpu': cpu_usage, '%memory': mem_usage}

def get_gpu_usage(client):
    _, stdout, _ = client.exec_command('nvidia-smi -q -x')
    xml_string = stdout.read()
    if len(xml_string) == 0:
        return {}

    xml = ET.fromstring(xml_string)
    result = []
    for gpu in xml.iter('gpu'):
        utilization = gpu.find('utilization')
        gpu_util = int(utilization.find('gpu_util').text.replace('%', ''))

        fb_memory_usage = gpu.find('fb_memory_usage')
        total_memory = int(fb_memory_usage.find('total').text.replace('MiB', ''))
        used_memory = int(fb_memory_usage.find('used').text.replace('MiB', ''))
        vram_util = 100 * used_memory // total_memory

        processes = gpu.find('processes')
        n_processes = len(processes.findall('process_info'))

        result.append({'gpu': gpu_util, 'vram': vram_util, 'n_processes': n_processes})
    return result

def analyze_status(client):
    return {
        'cpu_usage': get_cpu_usage(client),
        'gpu_usage': get_gpu_usage(client)
    }

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="dtop")
    parser.add_argument('--hosts', type=str, required=True, nargs="+", help="Target hosts")
    parser.add_argument('--user', '-u', type=str, required=True, help="Username for ssh connection")
    parser.add_argument('--ssh-config', '-c', type=str, default="~/.ssh/config", help="Path to ssh config")
    args = parser.parse_args()

    config = load_ssh_config(args.ssh_config)

    for host in args.hosts:
        with connect_ssh(config, host, args.user) as client:
            usage = analyze_status(client)
            cpu_usage = usage['cpu_usage']
            msg = "{}: CPU{:3d}%, RAM{:3d}%".format(host, cpu_usage['%cpu'], cpu_usage['%memory'])
            if usage['gpu_usage']:
                n_used_gpu = 0
                n_total_gpu = len(usage['gpu_usage'])
                for i, gpu_usage in enumerate(usage['gpu_usage']):
                    if gpu_usage['n_processes'] != 0:
                        n_used_gpu += 1
                    msg += " / GPU{}:{:3d}%, VRAM{:3d}%".format(i, gpu_usage['gpu'], gpu_usage['vram'])
                msg += " ({}/{} GPU used)".format(n_used_gpu, n_total_gpu)
            print(msg)

