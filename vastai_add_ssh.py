#!/Users/wojtess/Documents/powertrain/vastai-server-helper-scripts/vastai-env/bin/python3
from dotenv import load_dotenv
from vastai_sdk import VastAI
import os
from pathlib import Path
from simple_term_menu import TerminalMenu

load_dotenv()

def get_public_ssh_keys():
    """
    Odczytuje zawartość wszystkich publicznych kluczy SSH
    znalezionych w standardowym katalogu ~/.ssh/.

    Zwraca listę tupli (nazwa_pliku, zawartość_klucza).
    Zwraca pustą listę, jeśli katalog ~/.ssh/ nie istnieje
    lub nie zawiera plików .pub.
    """
    ssh_dir = Path.home() / ".ssh" # Konstruuje ścieżkę do katalogu ~/.ssh/

    # Sprawdź, czy katalog .ssh istnieje
    if not ssh_dir.is_dir():
        print(f"Ostrzeżenie: Katalog {ssh_dir} nie istnieje.")
        return []

    public_keys = []
    try:
        # Iteruj przez wszystkie elementy w katalogu ~/.ssh/
        for item in ssh_dir.iterdir():
            # Sprawdź, czy element jest plikiem i ma rozszerzenie .pub
            if item.is_file() and item.suffix == ".pub":
                try:
                    # Otwórz plik i odczytaj jego zawartość
                    with item.open("r", encoding="utf-8") as f:
                        key_content = f.read().strip() # Odczytaj i usuń białe znaki z początku/końca

                    # Dodaj nazwę pliku i zawartość klucza do listy
                    public_keys.append((item.name, key_content))
                except Exception as e:
                    print(f"Ostrzeżenie: Nie można odczytać pliku {item.name}: {e}")
                    # Kontynuuj, nawet jeśli jeden plik sprawia problem

    except Exception as e:
        print(f"Błąd podczas listowania plików w {ssh_dir}: {e}")
        return [] # Zwróć pustą listę w przypadku błędu podczas iteracji

    return public_keys

def main():
    vast_sdk = VastAI(api_key=os.environ.get("VASTAI_API_KEY"))
    # print(vast_sdk.list_machine(id))
    options = []
    for instance in vast_sdk.show_instances():
        options.append(f'id:{instance['id']}, {instance['geolocation']}, {instance['gpu_name']}')
    menu = TerminalMenu(options)
    selected_index = menu.show()
    instance_id = vast_sdk.show_instances()[selected_index]['id']
    ssh_keys = get_public_ssh_keys()
    options = []
    for key in ssh_keys:
        options.append(f'{key[0]}')
    menu = TerminalMenu(options)
    selected_index = menu.show()
    vast_sdk.attach_ssh(instance_id=instance_id, ssh_key=ssh_keys[selected_index][1])

if __name__=="__main__":
    main()