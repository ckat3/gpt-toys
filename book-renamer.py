import PySimpleGUI as sg
import gpt_lib as opr
import os
import threading
import re
import sys

KEY = "<your key>"

NAME_PATTERN = "Last-Name Other-Initials Original-Publication-Year <hyphen> Title<underscore> Subtitle"
UGLY_NAME    = "(Series or Other Information 36) John Doe - The Title of the Book, Part 2.1 - The Book's Subtitle-Publisher's Name (1954-1955) c"
PRETTY_NAME  = "Doe J 1954-55 - Title of the book, 2.1_ Book's subtitle"
MODELS = ["anthropic/claude-3.5-sonnet", "openai/gpt-4o"]

PROMPT = f"""
    You are a data processor and archivist.
    I will give you a numbered list of badly formatted book titles; you then format each line in the following way:\n
    Number:{NAME_PATTERN}\n
    So, for instance, the following line: \n 89:{UGLY_NAME}\n
    Should be reformatted as: \n 89:{PRETTY_NAME}\n
    Some information (such as the year, in the example above) might not be given for some books;
    in that case, if you know the correct data, fill it in and add an exclamation mark beside it.
    If a piece of information is not given and you don't know it yourself, then leave it blank. \n
    If a book has two authors, omit the initials of their first names.
    If a book has more than two authors, use only the first one's last name and add "et al". \n
    If a book's title or subtitle starts with a definite or indefinite article, omit that article.\n
    Your reply includes nothing but the formatted lines. Each line follows the format given above.
    It is thus a bare list of book entries: one book per line, one line per book.
    This list must be in the same order as the initial list I will give you. Do not omit, add, or reorder any entries.
    Here is the list:\n
"""

def create_agent(model, agents):
    agents[model] = opr.Gpt(model=model, assignment=PROMPT, key=KEY)

def send_list(files:list, agents:dict, cluster_size:int=10) -> None:
    numbered_names = [f"{n}:{file['name']}" for n, file in enumerate(files)]
    suggestions = {model: [] for model in MODELS}
    thread = {model: [] for model in MODELS}

    for model in MODELS:
            thread[model] = threading.Thread(target=query_agent,
                                             args=(agents, model, numbered_names, cluster_size, suggestions))
            thread[model].start()

    for model in MODELS:
            thread[model].join()

    for file in files:
        seen = set()
        seen.add(file["name"])
        print(f"{file['name'] =}")
        for model in MODELS: #todo this was probably just a very poor model acting up.
            s = suggestions[model].pop(0).strip()
            s = re.sub(r"   *", " ", s)
            try:
                s2 = s.split(':', 1)[1]
                if s2 not in seen:
                    file["new_names"][model] = s2
                    seen.add(s2)
            except IndexError:
                pass #TODO



def query_agent(agents:dict, model:str, array:list, cluster_size:int, output:dict) -> list:
    for n in range(0, len(array), cluster_size):
        message_cluster = "\n".join(array[n:n+cluster_size])
        response = agents[model].ask(message_cluster)
        output[model] += response.split("\n")

def new_full_name(file:dict, new_name:str=None, article:bool=False, anthology:bool=False) -> str:
    new_name = new_name or (list(file["new_names"].values())[0] if file["new_names"] else file["name"])

    if article:
        new_name = re.sub(r"_? - ", "_ - ", new_name)
    if anthology and not new_name.startswith("_"):
        new_name = f"_{new_name}"
    return f"{new_name}{file['ext']}"

def iterate(files:list) -> tuple:
    if not files:
        return None, None

    current_file = files.pop(0)
    if not current_file["new_names"]:
        return iterate(files)
    first_suggestion = new_full_name(current_file)
    return current_file, first_suggestion

def main() -> None:
    agents = {}
    agent_creation_threads = {}
    for model in MODELS:
        agent_creation_threads[model] = threading.Thread(target=create_agent, args=(model, agents,))
        agent_creation_threads[model].start()

    if True:
        folder = sg.popup_get_folder('Choose a folder')
        # files = [
        #     {"name": Path(filename).stem, "ext": Path(filename).suffix}
        #     for path, _, filenames in os.walk(folder)
        #     for filename in filenames
        # ]
        files = [{"name": os.path.splitext(filename)[0],
                  "ext":  os.path.splitext(filename)[1],
                  "new_names": {}}
                for __, ___, filenames in os.walk(folder)
                for filename in filenames]

        for model in MODELS:
            agent_creation_threads[model].join()

        send_list(files, agents)
        current_file, new_name = iterate(files)
        if current_file is None:
            print("nothing to do here!")
            sys.exit()

        llm_entries = [
            [sg.Button(k=f"-ADOPT-{model}", button_text=f"{model.split('/', 1)[-1]}", visible=(model in current_file["new_names"])),
             sg.InputText(key=model, default_text=current_file["new_names"].get(model, "nothing"),
                          expand_x=True, expand_y=True, enable_events=True,
                      #   visible=bool(current_file.get(model)))]
                          visible=(model in current_file["new_names"]))]
            for model in MODELS
        ]

        layout = [
            [sg.Text(key="-NAME-",   text=current_file["name"], expand_x=True, expand_y=True)]
        ] + llm_entries + [
            [sg.Text(key="-NEW_NAME-", text=new_name, expand_x=True, expand_y=True)],
            [sg.Button(k="-RENAME-", button_text="Rename"), sg.Button(k="-SKIP-", button_text="Skip"),
             sg.Checkbox(k="-ARTICLE-",   text='article',   default=False, enable_events=True),
             sg.Checkbox(k="-ANTHOLOGY-", text='anthology', default=False, enable_events=True)
            ]
        ]

        window = sg.Window(title="AI Renamer", layout=layout, margins=(50, 50), resizable=True, auto_size_text=True)

    try:
        while True:
            # nobody made any suggestions # TODO tidy up this loop
            if len(current_file["new_names"]) == 0:
                event = "-SKIP-"
                values = None
                window.read()

            else:
                event, values = window.read()

            if event == sg.WIN_CLOSED:
                break

            edited_field = event in MODELS
            chose_model = str(event).startswith("-ADOPT-")
            changed_checkbox = event in ["-ARTICLE-", "-ANTHOLOGY-"]

            if edited_field or chose_model or changed_checkbox:
                if edited_field:
                    chosen_name = values[event]
                elif chose_model:
                    chosen_name = values[str(event).split("-ADOPT-")[1]]
                elif changed_checkbox:
                    chosen_name = None
                new_name = new_full_name(current_file, chosen_name,
                                         values["-ARTICLE-"], values["-ANTHOLOGY-"])

                window["-NEW_NAME-"].update(new_name)

            if event == "-RENAME-":
                # original_path = Path(folder) / f"{current_file['name']}{current_file['ext']}"
                # renamed_path = Path(folder) / new_name
                original_path = os.path.join(folder, current_file["name"] + current_file["ext"])
                renamed_path  = os.path.join(folder, new_name)

                print(f"Renaming:\n    {original_path}\n  > {renamed_path}\n")
                os.rename(original_path, renamed_path)

            if event in ["-SKIP-", "-RENAME-"]:
                current_file, new_name = iterate(files)
                if current_file is None:
                    print("bye bye!")
                    break

                for model in MODELS:
                    suggestion = current_file["new_names"].get(model, "")
                    visible = bool(suggestion)
                    window[f"-ADOPT-{model}"].update(visible=visible)
                    window[model].update(suggestion, visible=visible)

                window["-NAME-"].update(current_file["name"])
                window["-NEW_NAME-"].update(new_name)

    finally:
        window.close()

if __name__ == "__main__":
    main()
