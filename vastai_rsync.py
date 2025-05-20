#!/home/wojtess/Documents/powertrain/server-vastai/vastai-env/bin/python3
from dotenv import load_dotenv
from vastai_sdk import VastAI
import os
import sys
from simple_term_menu import TerminalMenu
from pathlib import Path
import paramiko # Choć paramiko jest zaimportowane, nie jest używane w tym przepływie rsync
import datetime
import requests
import subprocess # Dodany import modułu subprocess

load_dotenv()

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
            # Sprawdź, czy element jest plikiem i nie ma rozszerzenia .pub oraz nie jest 'known_hosts' ani 'config'
            # Chcemy pliki kluczy prywatnych, np. id_rsa, id_ed25519
            if item.is_file() and item.suffix != ".pub" and item.name not in ["known_hosts", "config"]:
                # Dodajemy nazwę pliku (bez ścieżki) oraz pełną ścieżkę do klucza
                keys.append((item.name, str(item.resolve())))

    except Exception as e:
        print(f"Błąd podczas listowania plików w {ssh_dir}: {e}")
        return [] # Zwróć pustą listę w przypadku błędu podczas iteracji
    
    if not keys:
        print(f"Nie znaleziono prywatnych kluczy SSH w {ssh_dir}. Upewnij się, że pliki kluczy (np. id_rsa, id_ed25519) tam są.")

    return keys


def main():
    # Zmieniono logikę sprawdzania argumentów, aby gitignore_file był opcjonalny
    if len(sys.argv) < 3 or len(sys.argv) > 4:
        print(f'Użycie: {sys.argv[0]} <katalog_zrodlowy> <katalog_docelowy_na_serwerze> [sciezka_do_pliku_gitignore]')
        print(f'Przykład 1 (z .gitignore): {sys.argv[0]} ./moj_projekt /root/deployment ./.gitignore')
        print(f'Przykład 2 (bez .gitignore): {sys.argv[0]} ./moj_projekt /root/deployment')
        return
    
    src = sys.argv[1]
    dst = sys.argv[2]
    gitignore_file_path_arg = None # Domyślnie brak pliku .gitignore
    if len(sys.argv) == 4:
        gitignore_file_path_arg = sys.argv[3]
        # Sprawdzenie, czy podany plik .gitignore istnieje, jeśli został podany
        if not Path(gitignore_file_path_arg).is_file():
            print(f"BŁĄD: Plik .gitignore '{gitignore_file_path_arg}' nie został znaleziony.")
            return
        
    # Sprawdzenie, czy katalog źródłowy istnieje
    if not Path(src).is_dir():
        print(f"BŁĄD: Katalog źródłowy '{src}' nie został znaleziony.")
        return

    vast_sdk = VastAI(api_key=os.environ.get("VASTAI_API_KEY"))
    
    print("Pobieranie listy instancji...")
    instances = vast_sdk.show_instances()
    if not instances: 
        print('Brak aktywnych instancji na Vast.ai.')
        return

    options = []
    for instance in instances:
        options.append(f"ID: {instance['id']}, Lokalizacja: {instance.get('geolocation', 'N/A')}, GPU: {instance.get('gpu_name', 'N/A')}, Status: {instance.get('actual_status', 'N/A')}")
    
    if not options:
        print('Brak instancji do wyboru (mogą być w nieodpowiednim stanie).')
        return

    print("\nWybierz instancję docelową:")
    menu = TerminalMenu(options)
    selected_index = menu.show()
    
    if selected_index is None:
        print("Nie wybrano instancji. Przerywam.")
        return

    instance_id = instances[selected_index]['id']

    print(f'\nWybrano instancję o ID: {instance_id}')
    
    instance_info_initial = vast_sdk.show_instance(id=instance_id)
    if instance_info_initial.get('actual_status') != 'running':
        print(f"Instancja {instance_id} nie jest uruchomiona (status: {instance_info_initial.get('actual_status')}). Próba uruchomienia...")
        vast_sdk.start_instance(id=instance_id)
        print("Zażądano uruchomienia instancji. Odczekaj chwilę i spróbuj ponownie, jeśli rsync się nie powiedzie, lub dodaj logikę oczekiwania na status 'running'.")

    print("Pobieranie szczegółów instancji (w tym portu SSH)...")
    instance_info = vast_sdk.show_instance(id=instance_id)

    ssh_port_info = instance_info.get('ports', {}).get('22/tcp')
    if not ssh_port_info or not isinstance(ssh_port_info, list) or not ssh_port_info[0].get('HostPort'):
        print(f"BŁĄD: Nie można uzyskać informacji o porcie SSH dla instancji {instance_id}.")
        print("Upewnij się, że instancja jest poprawnie skonfigurowana i uruchomiona.")
        print(f"Dane portów: {instance_info.get('ports')}")
        return
        
    host_port = ssh_port_info[0]['HostPort']
    public_ip = instance_info.get('public_ipaddr')
    ssh_user = instance_info.get('ssh_user', 'root') 

    if not public_ip:
        print(f"BŁĄD: Brak publicznego adresu IP dla instancji {instance_id}.")
        return

    print(f"Instancja {instance_id} jest dostępna pod adresem {public_ip} na porcie {host_port} (użytkownik SSH: {ssh_user}).")

    ssh_keys = get_private_ssh_keys()
    if not ssh_keys:
        print("BŁĄD: Nie znaleziono kluczy SSH. Upewnij się, że masz skonfigurowane klucze w ~/.ssh/")
        return

    key_options = [f"{key_info[0]} (plik: {key_info[1]})" for key_info in ssh_keys]
    
    print("\nWybierz klucz SSH do autoryzacji:")
    key_menu = TerminalMenu(key_options)
    selected_key_index = key_menu.show()

    if selected_key_index is None:
        print("Nie wybrano klucza SSH. Przerywam.")
        return
        
    selected_key_path = ssh_keys[selected_key_index][1]
    print(f"Wybrano klucz SSH: {selected_key_path}")
    
    abs_src_path = Path(src).resolve()

    rsync_command_parts = [
        "rsync",
        "-avz",
        "-e", f"ssh -i {selected_key_path} -p {host_port} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null",
        "--exclude=.git",
        "--info=progress2"
    ]

    # Dodaj --exclude-from=plik_gitignore jeśli plik został podany
    if gitignore_file_path_arg:
        abs_gitignore_path = Path(gitignore_file_path_arg).resolve()
        rsync_command_parts.append(f"--exclude-from={abs_gitignore_path}")
        print(f"Używam pliku '{abs_gitignore_path}' dla opcji --exclude-from.")
    else:
        print("Nie podano pliku .gitignore, pomijam opcję --exclude-from.")

    rsync_command_parts.extend([
        f"{abs_src_path}/", 
        f"{ssh_user}@{public_ip}:{dst}/"
    ])

    print("\nPrzygotowane polecenie rsync:")
    print(" ".join(rsync_command_parts)) 

    print(f"\nRozpoczynanie transferu rsync z '{abs_src_path}/' do '{ssh_user}@{public_ip}:{dst}/'...")
    
    try:
        process = subprocess.run(rsync_command_parts, capture_output=True, text=True, check=True)
        
        print("\n--- Dane wyjściowe rsync (stdout) ---")
        print(process.stdout)
        print("--- Koniec stdout ---")
        
        if process.stderr: 
            print("\n--- Dane wyjściowe rsync (stderr) ---")
            print(process.stderr)
            print("--- Koniec stderr ---")
            
        print("\nTransfer rsync zakończony pomyślnie!")

    except subprocess.CalledProcessError as e:
        print("\nBŁĄD podczas wykonywania rsync!")
        print(f"Kod powrotu: {e.returncode}")
        print("\n--- stdout ---")
        print(e.stdout)
        print("\n--- stderr ---")
        print(e.stderr)
    except FileNotFoundError:
        print("BŁĄD: Polecenie 'rsync' nie zostało znalezione. Upewnij się, że rsync jest zainstalowany i dostępny w PATH.")
    except Exception as e:
        print(f"Wystąpił nieoczekiwany błąd: {e}")


if __name__=="__main__":
    main()
