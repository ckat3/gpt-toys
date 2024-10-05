from gpt_lib import Gpt
import os
import sys
import tempfile
import psutil
import pyperclip
import time
import pickle
import keyboard
import threading
from windows_toasts import Toast, WindowsToaster, ToastDuration

SERVER_TIMEOUT = 600
MODEL = "gpt-4o"
DEFAULT_L2 = "Brazilian Portuguese"

assignment = "Translate the given text into the language first given between brackets."\
             "Output nothing but the translated text."

tempdir  = tempfile.gettempdir()
PIDFILE  = os.path.join(tempdir, "gpt_translator.pid")  # when exists, the server is running
CALLFILE = os.path.join(tempdir, "gpt_translator.call") # when exists, the server is called to action
STRMFILE = os.path.join(tempdir, "gpt_translator.streaming") # when exists, the server is currently receiving a stream

def announce_completion(t0):
    print(f"  completed in [{time.time() - t0:.1f}] s\n")
    return time.time()

def remove_if_exists(*args:list[str]) -> None:
    for filepath in args:
        try:
            os.remove(filepath)
        except FileNotFoundError:
            pass


class Toaster(WindowsToaster):
    def __init__(self, name):
        super().__init__(name)

    def __call__(self, text, attribution_text=None, duration=ToastDuration.Long, clear=True):
        if clear:
            self.clear_toasts()

        print(f"{[text]}")
        if attribution_text:
            print(f"{attribution_text}\n")
        print()

        if attribution_text:
            attribution_text = attribution_text[:500]

        toast = Toast([text[:500]], attribution_text=attribution_text, duration=duration)
        self.show_toast(toast)


class Translator_Server:
    def __init__(self, target_language:str, assignment:str, modes:str, toaster:Toaster):
        toaster(f"Initializing server…")

        self.target_language = target_language
        self.modes = modes
        self.last_query = None
        self.gpt = Gpt(assignment)
        self.toaster = toaster
        self.writing_queue = ''
        self.writing_thread = threading.Thread()
        self.pid = str(os.getpid())

        with open(PIDFILE, "w") as pidfile:
            pidfile.write(self.pid)

        remove_if_exists(STRMFILE) #TODO test for pid

        if "silent" not in self.modes:
            self.translate()


    def loop(self):
        self.last_query = time.time()
        try:
            while True:
                if time.time() - self.last_query > SERVER_TIMEOUT:
                    print(f"Server timed out after {SERVER_TIMEOUT} seconds.")
                    break

                call = self.get_call()
                while not call:
                    time.sleep(.1)

                self.modes.update(call)

                try:
                    self.translate()
                except ValueError as e:
                    print(f"<<Error: {e}>>")

        finally:
            remove_if_exists(PIDFILE, CALLFILE, STRMFILE)

    def get_call(self):
        if os.path.isfile(CALLFILE):
            calling_modes = load_pickle(CALLFILE)
            # with open(CALLFILE, "rb") as callfile:
            #     calling_modes = pickle.load(callfile)
            print(f"Called to action: {calling_modes}, previously {self.modes}")
            os.remove(CALLFILE)
            return calling_modes

        return {}

    def write(self, text, min_length=10): # TODO
        self.writing_queue += text
        if len(self.writing_queue) > min_length:
            if (self.writing_thread.is_alive()):
                self.writing_thread.join()
            # keyboard.write(self.writing_queue)
            self.writing_thread = threading.Thread(target=keyboard.write, args=(text,))
            self.writing_thread.start()
            self.writing_queue = ""

    def unload_queue(self):
        if self.writing_queue:
            queue = ""
            # keyboard.write(queue)
            print(f"<<{queue}>>", end='')
            self.writing_queue = ""

    def translate(self, input:str=None):
        if "paste" in self.modes:
            return

        with open(STRMFILE, "w") as strmfile:
            strmfile.write(self.pid)

        input = pyperclip.paste() if input is None else input # TODO not here
        input = input.strip()

        if not input:
            raise ValueError("no input")

        self.toaster(f"Translating to {self.target_language}…", input)

        stream = threading.Thread(target=self.gpt.query,
                                  args=(f"[{self.target_language}] {input}",),
                                  kwargs={"stream": True}
                                 )
        stream.start()
        self.toaster("one sec")
        time.sleep(1)

        translation = ''
        self.toaster("GO")
        while (not self.gpt.done) or self.gpt.pending_chunks:
            current_chunks = self.gpt.pop_chunks()
            translation += current_chunks

            if not "paste" in self.modes and not "write" in self.modes:
                if True or "paste" in self.get_call():
                    print(f"<<{translation}>>", end='')
                    self.write(translation)
                    self.modes.add("write")

            elif current_chunks and "write" in self.modes:
                print(f"<<{current_chunks}>>", end='')
                # keyboard.write(current_chunks)
                self.write(current_chunks)



            # if self.gpt.received_stream:
            #     n = len(translation)
            #     current_chunks = self.gpt.received_stream[n:]
            #     if current_chunks:
            #         translation += current_chunks
            #         self.get_call()
            #         if "write" in self.modes:
            #             # print(f"<<{current_chunks}>>", end='')
            #             self.write(current_chunks)
            #         elif "paste" in self.modes:
            #             self.write(translation)
            #             self.modes.add("write")

        os.remove(STRMFILE)
        if self.writing_thread.is_alive():
            self.writing_thread.join()
        self.write(self.writing_queue, min_length=1)

        if "write" not in self.modes:
            stream.join()

        if "copy" in self.modes:
            pyperclip.copy(translation)
            self.toaster(f"Translation copied to clipboard", translation, duration=ToastDuration.Short)

        else:
            self.toaster(f"Translated", translation)

        self.modes = set()
        self.last_query = time.time()

    # @atexit.register
    # def clean_up(self):
    #     remove_if_exists(STRMFILE, PIDFILE, CALLFILE)

def server_running(pidfile_path):
    if os.path.isfile(pidfile_path):
        with open(pidfile_path, "r") as pidfile:
            pid = int(pidfile.read())
            if psutil.pid_exists(pid):
                return True

        # remove outdated pidfile
        os.remove(pidfile_path)

    return False

def read_args():
    all_modes = {"-c": "copy", "-w": "write", "-v": "paste", "-s": "silent"}
    return {mode for arg, mode in all_modes.items() if arg in sys.argv[1:]}

    # modes = set()
    # for arg in sys.argv[1:]: # TODO
    #     if arg in all_modes:
    #         modes.add(all_modes[arg])

def load_pickle(filepath:str) -> any:
    with open(filepath, "rb") as file:
        return pickle.load(file)

def write_pickle(filepath:str, content:any) -> None:
    with open(filepath, "wb") as file:
        pickle.dump(content, file)

def main():
    # if "-v" in sys.argv[1:]:
    #     write_pickle(CALLFILE, {"paste"})
    #     # with open(CALLFILE, "wb") as callfile:
    #     #     pickle.dump({"paste"}, callfile) # just write it either way — for speed

    #     if not server_running(PIDFILE): # if there was no server, then paste and delete it I guess
    #         pyperclip.paste()
    #         remove_if_exists(CALLFILE)

    #     return

    toaster = Toaster("GPTrad")

    # TODO give this a place
    # TODO handle multiple callfiles
    modes = read_args()
    is_client = server_running(PIDFILE)

    if is_client:
        print(f"Server already running. Calling it to action: {modes}")
        write_pickle(CALLFILE, modes)
        return

    elif "paste" in modes:
        print(f"Pasting: {pyperclip.paste()}")
        keyboard.write(pyperclip.paste())

    else:
        server = Translator_Server(DEFAULT_L2, assignment, modes, toaster)
        try:
            server.loop()
        except (SystemExit, KeyboardInterrupt):
            remove_if_exists(PIDFILE, CALLFILE, STRMFILE)


if __name__ == "__main__":
    main()