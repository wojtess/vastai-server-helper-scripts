from dotenv import load_dotenv
from vastai_sdk import VastAI
import os
from simple_term_menu import TerminalMenu

load_dotenv()

def main():
    vast_sdk = VastAI(api_key=os.environ.get("VASTAI_API_KEY"))
    # print(vast_sdk.list_machine(id))
    options = []
    for instance in vast_sdk.show_instances():
        options.append(f'id:{instance['id']}, {instance['geolocation']}, {instance['gpu_name']}')
    menu = TerminalMenu(options)
    selected_index = menu.show()
    instance_id = vast_sdk.show_instances()[selected_index]['id']
    print(f'Starting isnatnce with ID: {instance_id}')
    vast_sdk.start_instance(ID=instance_id)


if __name__=="__main__":
    main()