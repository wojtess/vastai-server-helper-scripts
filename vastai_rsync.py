#!/Users/wojtess/Documents/powertrain/vastai-server-helper-scripts/vastai-env/bin/python3
from dotenv import load_dotenv
from vastai_sdk import VastAI
import os
import sys
from simple_term_menu import TerminalMenu # Pozostawione dla wyboru instancji i klucza SSH
from pathlib import Path
import subprocess

load_dotenv()

def get_private_ssh_keys():
    ssh_dir = Path.home() / ".ssh"
    if not ssh_dir.is_dir():
        print(f"Ostrzeżenie: Katalog {ssh_dir} nie istnieje.")
        return []
    keys = []
    try:
        for item in ssh_dir.iterdir():
            if item.is_file() and item.suffix != ".pub" and item.name not in ["known_hosts", "config"]:
                keys.append((item.name, str(item.resolve())))
    except Exception as e:
        print(f"Błąd podczas listowania plików w {ssh_dir}: {e}")
        return []
    if not keys:
        print(f"Nie znaleziono prywatnych kluczy SSH w {ssh_dir}.")
    return keys

def print_usage():
    script_name = sys.argv[0]
    print(f'\nUżycie: {script_name} <operacja> <ścieżka1> <ścieżka2> [--dry-run] [plik_wykluczen_lokalny]')
    print("\nArgumenty:")
    print("  <operacja>                : 'upload' (wysyłanie) lub 'download' (pobieranie).")
    print("  <ścieżka1>                : Zależna od operacji:")
    print("                            Dla 'upload': Lokalny katalog źródłowy.")
    print("                            Dla 'download': Zdalny katalog źródłowy na serwerze.")
    print("  <ścieżka2>                : Zależna od operacji:")
    print("                            Dla 'upload': Zdalny katalog docelowy na serwerze.")
    print("                            Dla 'download': Lokalny katalog docelowy.")
    print("  --dry-run                 : (Opcjonalnie) Wyświetla komendę rsync bez jej wykonywania.")
    print("  [plik_wykluczen_lokalny]: (Opcjonalnie) Lokalny plik .gitignore lub podobny (dla --exclude-from).")
    print("\nPrzykłady:")
    print(f'  Wysyłanie:        {script_name} upload ./moj_projekt /home/user/na_serwerze ./.gitignore')
    print(f'  Pobieranie:       {script_name} download /home/user/na_serwerze ./pobrane_pliki')
    print(f'  Wysyłanie dry-run: {script_name} upload ./moj_projekt /home/user/na_serwerze --dry-run ./.gitignore')

def main():
    args = sys.argv[1:] # Pomijamy nazwę skryptu

    if not args or args[0] in ['-h', '--help']:
        print_usage()
        return

    # Parsowanie --dry-run
    is_dry_run = False
    if "--dry-run" in args:
        is_dry_run = True
        args.remove("--dry-run") # Usuń --dry-run z listy argumentów do dalszego parsowania
        print("Wybrano tryb: Tylko pokaż komendę (Dry Run)")
    else:
        print("Wybrano tryb: Normalne wykonanie")

    # Sprawdzenie minimalnej liczby argumentów po usunięciu --dry-run
    # Potrzebujemy: operacja, ścieżka1, ścieżka2 (minimum 3)
    if len(args) < 3:
        print("BŁĄD: Niewystarczająca liczba argumentów.")
        print_usage()
        return

    selected_operation = args[0].lower()
    if selected_operation not in ["upload", "download"]:
        print(f"BŁĄD: Nieznana operacja '{selected_operation}'. Dostępne: 'upload', 'download'.")
        print_usage()
        return
    
    path1_arg = args[1]
    path2_arg = args[2]
    
    exclude_file_path_arg = None
    if len(args) == 4: # Jeśli jest czwarty argument (po operacji, path1, path2), to jest to plik wykluczeń
        exclude_file_path_arg = args[3]
        if not Path(exclude_file_path_arg).is_file():
            print(f"BŁĄD: Lokalny plik wykluczeń '{exclude_file_path_arg}' nie został znaleziony.")
            return
    elif len(args) > 4:
        print("BŁĄD: Zbyt wiele argumentów.")
        print_usage()
        return

    # Walidacja ścieżek w zależności od trybu
    if selected_operation == "upload":
        if not Path(path1_arg).is_dir():
            print(f"BŁĄD: Lokalny katalog źródłowy '{path1_arg}' (ścieżka1) nie został znaleziony dla operacji wysyłania.")
            return
    
    print(f"\nWybrana operacja: {selected_operation.capitalize()}")

    vast_sdk = VastAI(api_key=os.environ.get("VASTAI_API_KEY"))
    
    print("\nPobieranie listy instancji...")
    instances = vast_sdk.show_instances()
    if not instances: 
        print('Brak aktywnych instancji na Vast.ai.')
        return

    instance_options_display = []
    for instance in instances:
        instance_options_display.append(f"ID: {instance['id']}, Lokalizacja: {instance.get('geolocation', 'N/A')}, GPU: {instance.get('gpu_name', 'N/A')}, Status: {instance.get('actual_status', 'N/A')}")
    
    if not instance_options_display:
        print('Brak instancji do wyboru (mogą być w nieodpowiednim stanie).')
        return

    print("\nWybierz instancję docelową:")
    instance_menu = TerminalMenu(instance_options_display)
    selected_instance_idx = instance_menu.show()
    
    if selected_instance_idx is None:
        print("Nie wybrano instancji. Przerywam.")
        return

    instance_id = instances[selected_instance_idx]['id']

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

    key_options_display = [f"{key_info[0]} (plik: {key_info[1]})" for key_info in ssh_keys]
    
    print("\nWybierz klucz SSH do autoryzacji:")
    key_menu = TerminalMenu(key_options_display)
    selected_key_idx = key_menu.show()

    if selected_key_idx is None:
        print("Nie wybrano klucza SSH. Przerywam.")
        return
        
    selected_key_path = ssh_keys[selected_key_idx][1]
    print(f"Wybrano klucz SSH: {selected_key_path}")
    
    # Konstrukcja polecenia rsync
    rsync_base_command_parts = [
        "rsync",
        "-avz",
        "-e", f"ssh -i {selected_key_path} -p {host_port} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null",
        "--exclude=.git" 
    ]

    if exclude_file_path_arg:
        abs_exclude_file_path = Path(exclude_file_path_arg).resolve()
        rsync_base_command_parts.append(f"--exclude-from={abs_exclude_file_path}")
        print(f"Używam pliku '{abs_exclude_file_path}' dla opcji --exclude-from.")
    else:
        print("Nie podano pliku wykluczeń, pomijam opcję --exclude-from.")

    rsync_final_command_parts = []
    transfer_src_display = ""
    transfer_dst_display = ""

    if selected_operation == "upload":
        local_src_path = Path(path1_arg).resolve()
        remote_dst_path_str = path2_arg 

        rsync_final_command_parts = rsync_base_command_parts + [
            f"{local_src_path}/", 
            f"{ssh_user}@{public_ip}:{remote_dst_path_str}/"
        ]
        transfer_src_display = str(local_src_path)
        transfer_dst_display = f"{ssh_user}@{public_ip}:{remote_dst_path_str}"
        print(f"\nTryb: Wysyłanie (Upload)")

    elif selected_operation == "download":
        remote_src_path_str = path1_arg 
        local_dst_path = Path(path2_arg).resolve()

        try:
            local_dst_path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            print(f"BŁĄD: Nie można utworzyć lokalnego katalogu docelowego '{local_dst_path}': {e}")
            return

        rsync_final_command_parts = rsync_base_command_parts + [
            f"{ssh_user}@{public_ip}:{remote_src_path_str}/",
            f"{local_dst_path}/"
        ]
        transfer_src_display = f"{ssh_user}@{public_ip}:{remote_src_path_str}"
        transfer_dst_display = str(local_dst_path)
        print(f"\nTryb: Pobieranie (Download)")


    print("\nPrzygotowane polecenie rsync:")
    print(" ".join(rsync_final_command_parts)) 

    if is_dry_run:
        print("\nTRYB DRY RUN: Polecenie nie zostanie wykonane.")
        return # Zakończ funkcję main, jeśli to dry run

    print(f"\nRozpoczynanie transferu rsync z '{transfer_src_display}/' do '{transfer_dst_display}/'...")
    
    try:
        process = subprocess.run(rsync_final_command_parts, capture_output=True, text=True, check=True)
        
        print("\n--- Dane wyjściowe rsync (stdout) ---")
        print(process.stdout)
        print("--- Koniec stdout ---")
        
        if process.stderr: 
            print("\n--- Dane wyjściowe rsync (stderr) ---")
            print(process.stderr)
            print("--- Koniec stderr ---")
            
        print(f"\nTransfer rsync ({selected_operation}) zakończony pomyślnie!")

    except subprocess.CalledProcessError as e:
        print(f"\nBŁĄD podczas wykonywania rsync ({selected_operation})!")
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
