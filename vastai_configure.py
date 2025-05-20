#!/home/wojtess/Documents/powertrain/server-vastai/vastai-env/bin/python3
from dotenv import load_dotenv
from vastai_sdk import VastAI
import os
from simple_term_menu import TerminalMenu
from pathlib import Path
import paramiko 
import datetime
import requests

load_dotenv()

class TailscaleAPI:
    def __init__(self, api_key, tailnet_name="", api_url="https://api.tailscale.com/api/v2"):
        self.tailnet_name = tailnet_name
        
        self.tskey = api_key
        
        # Ustawienie nagłówka autoryzacji
        self.headers = {
            "Authorization": f"Bearer {self.tskey}",
            "Content-Type": "application/json"
        }
        
        # Ustawienie podstawowego URL API
        self.api_url = api_url

    def get_devices(self):
        url = f"{self.api_url}/tailnet/{self.tailnet_name}/devices"
        response = requests.get(url, headers=self.headers)
        return self._handle_response(response)

    def get_device(self, device_id):
        url = f"{self.api_url}/device/{device_id}"
        response = requests.get(url, headers=self.headers)
        return self._handle_response(response)

    def delete_device(self, device_id):
        url = f"{self.api_url}/device/{device_id}"
        response = requests.delete(url, headers=self.headers)
        return self._handle_response(response)

    def create_key(self, payload, querystring=None):
        url = f"{self.api_url}/tailnet/{self.tailnet_name}/keys"
        response = requests.post(url, json=payload, headers=self.headers, params=querystring)
        return self._handle_response(response)

    def _handle_response(self, response):
        if response.status_code == 200:
            return response.json()
        else:
            response.raise_for_status()

commands = [
    "apt update",
    # "apt install -y xfce4 xfce4-goodies tightvncserver"
]

def get_private_ssh_keys():
    ssh_dir = Path.home() / ".ssh" # Konstruuje ścieżkę do katalogu ~/.ssh/

    # Sprawdź, czy katalog .ssh istnieje
    if not ssh_dir.is_dir():
        print(f"Ostrzeżenie: Katalog {ssh_dir} nie istnieje.")
        return []

    keys = []
    try:
        # Iteruj przez wszystkie elementy w katalogu ~/.ssh/
        for item in ssh_dir.iterdir():
            # Sprawdź, czy element jest plikiem i ma rozszerzenie .pub
            if item.is_file() and item.suffix == ".pub":
                keys.append((item.name[:-4], f'{ssh_dir / item.name[:-4]}'))

    except Exception as e:
        print(f"Błąd podczas listowania plików w {ssh_dir}: {e}")
        return [] # Zwróć pustą listę w przypadku błędu podczas iteracji

    return keys


def main():
    vast_sdk = VastAI(api_key=os.environ.get("VASTAI_API_KEY"))
    options = []
    for instance in vast_sdk.show_instances():
        options.append(f'id:{instance['id']}, {instance['geolocation']}, {instance['gpu_name']}')
    menu = TerminalMenu(options)
    selected_index = menu.show()
    instance_id = vast_sdk.show_instances()[selected_index]['id']

    print(f'Starting isnatnce with ID: {instance_id}')
    vast_sdk.start_instance(id=instance_id)
    instance_info = vast_sdk.show_instance(id=instance_id)

    ssh_keys = get_private_ssh_keys()
    options = []
    for key in ssh_keys:
        options.append(f'{key[0]}')
    menu = TerminalMenu(options)
    selected_index = menu.show()

    Path('logs').mkdir(parents=True, exist_ok=True)
    stdout_file = open('logs/stdout.txt', 'a+')
    stderr_file = open('logs/stderr.txt', 'a+')
    stdout_file.writelines([f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"])
    stderr_file.writelines([f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"])


    ssh_client = paramiko.client.SSHClient()        
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    pkey = paramiko.RSAKey.from_private_key_file(ssh_keys[selected_index][1])
    ssh_client.connect(instance_info['public_ipaddr'], username='root', pkey=pkey, port=instance_info['ports']['22/tcp'][0]['HostPort'])

    tailscape = TailscaleAPI(api_key=os.environ.get('TAILSCAPE_API_KEY'), tailnet_name=os.environ.get('TAILSCALE_TAILNET_NAME'))
    response = tailscape.create_key(
        {
            "description": "dev access",
            "capabilities": { "devices": { "create": {
                        "reusable": True,
                        "ephemeral": False,
                        "preauthorized": True
                    } } },
            "expirySeconds": 86400,
            "scopes": ["all:read"]
        },
        {"all": True}
    )
    commands.append(f'curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up --auth-key={response['key']} --hostname={instance_info['geolocation'].replace(' ', '-').replace(',', '')}-{instance_info['gpu_name'].replace(' ','-')}')
    commands.append(f'tailscale up')

    for command in commands:
        print(f'executing command: {command}')
        stdin, stdout, stderr = ssh_client.exec_command(command=command)
        stdout_file.writelines(f'{stdout.read().decode('utf-8')}\n')
        stderr_file.writelines(f'{stderr.read().decode('utf-8')}\n')

    


if __name__=="__main__":
    main()