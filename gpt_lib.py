import openai
import time

DEFAULT_MODEL = "gpt-4o"
DEFAULT_TEMP = 1
DEFAULT_REQ_TIMEOUT = 10 #seconds

class Gpt:
    def __init__(self,
                 assignment:str="",
                 stream_by_default:bool=False,
                 sample_exchanges:list[str]=None,
                 model:str=None,
                 temperature:float=None,
                 query_timeout:int=None,
                 base_url:str=None,
                 key:str=None) -> None:

        self.client = openai.OpenAI(api_key=key, base_url=base_url) #TODO timeout

        self.model = model or DEFAULT_MODEL
        self.temperature = temperature or DEFAULT_TEMP
        self.query_timeout = query_timeout or DEFAULT_REQ_TIMEOUT

        self.stream_by_default = stream_by_default
        self.done_streaming = False
        self.current_stream = '' # this can be popped to the client
        self.assembled_stream = '' # the full streamed reply, regardless of the above

        self.received_reply = ''

        self.context = [self.format("system", assignment)] if assignment else []

        while sample_exchanges:
            user_message      = sample_exchanges.pop(0)
            assistant_message = sample_exchanges.pop(0)
            self.context.extend([self.format("user",      user_message),
                                 self.format("assistant", assistant_message)])

    def format(self, role:str, content:str) -> dict:
        """
        Syntactic sugar for passing messages to the API.
        Roles con be "system", "user", or "assistant".
        """

        return {"role": role, "content": content}

    def update_context(self, message:dict[str], updated_context:list[dict]=None) -> None:
        # TODO: currently unused
        self.context = (updated_context or self.context) + [message]

    def pop_chunks(self) -> str:
        popped = self.current_stream
        self.current_stream = self.current_stream[len(popped):]
        return popped

    def query(self, message:str, stream:bool=None, temperature:float=None):
        self.received_reply = ''
        self.last_query_time = time.time()
        stream = stream if stream is not None else self.stream_by_default
        temperature = temperature if temperature is not None else self.temperature

        contextualized_query = self.context + [self.format("user", message)]

        try:
            reply = self.create_completion(contextualized_query, stream, temperature)
            # self.context = contextualized_query + [self.format("assistant", reply)]
            self.received_reply = reply

        except openai.APIConnectionError:
            self.received_reply = "Connection error."

        except Exception as e:
            self.received_reply = f"Error: {e}"

        finally:
            return self.received_reply

            # else:
            #     time_elapsed = time.time() - self.last_query_time
            #     if time_elapsed > self.query_timeout:
            #         return f"Query timed out after {time_elapsed} s."

    def create_completion(self, messages, stream, temperature) -> None:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=stream,
            temperature=temperature,
        )

        if stream:
            if not self.done_streaming:
                raise Exception("There is already a completion being streamed.")

            return self.stream_completion(response)

        else:
            return response.choices[0].message.content

    def stream_completion(self, response) -> str:
        """
        Runs asynchronously, incorporating the received stream into the
        object so that a client can pop out its current state and iteratively
        process the stream before its done.
        """

        self.done_streaming = False
        self.current_stream = ''
        self.assembled_stream = ''

        for chunk in response:
        # TODO how does this work on the api? when does it stop?
            choice = chunk.choices[0]
            delta = choice.delta.content
            if delta is not None:
                self.current_stream += delta
                self.assembled_stream += delta

        self.done_streaming = True

        return self.assembled_stream

    def loop(self) -> None:
        integer_temp = 0

        # last_input = ""
        while True:
            new_input = input("> ").strip()
            if new_input:
                integer_temp = 0
                last_input = new_input
            else:
                integer_temp += 2 # if blank then regenerate, but hotter

            if last_input:
                reply = self.ask( last_input, (integer_temp%11)/10 ) # magic lost to oblivion
                print("\n" + reply)


if __name__ == '__main__':
    Gpt().loop()