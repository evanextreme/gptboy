import base64
import collections
from datetime import datetime
import math
import re
import threading
from io import BytesIO
from openai import OpenAI
from pyboy import WindowEvent
from pyboy import PyBoy
import os

TICKS_PER_SECOND = 60
TICKS_PER_MINUTE = math.pow(TICKS_PER_SECOND,2)
ACTIONS_N_SECONDS = 1
PROMPT_N_SECONDS = 120
SAVE_N_SECONDS = 300
REGENERATION_MODE_MULTIPLE = 5

WINDOW_EVENTS = {
    "START": (WindowEvent.PRESS_BUTTON_START, WindowEvent.RELEASE_BUTTON_START),
    "SELECT": (WindowEvent.PRESS_BUTTON_SELECT, WindowEvent.RELEASE_BUTTON_SELECT),
    "A": (WindowEvent.PRESS_BUTTON_A, WindowEvent.RELEASE_BUTTON_A),
    "B": (WindowEvent.PRESS_BUTTON_B, WindowEvent.PRESS_BUTTON_B),
    "UP": (WindowEvent.PRESS_ARROW_UP, WindowEvent.RELEASE_ARROW_UP),
    "DOWN": (WindowEvent.PRESS_ARROW_DOWN, WindowEvent.RELEASE_ARROW_DOWN),
    "LEFT": (WindowEvent.PRESS_ARROW_LEFT, WindowEvent.RELEASE_ARROW_LEFT),
    "RIGHT": (WindowEvent.PRESS_ARROW_RIGHT, WindowEvent.RELEASE_ARROW_RIGHT),
}

ALL_ACTIONS = list(WINDOW_EVENTS.keys())

def image_to_bytes(image):
    jpeg_mafia = image.convert("RGB")
    buffered = BytesIO()
    jpeg_mafia.save(buffered, format="JPEG")
    image_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
    return image_str

def compare_base64(base64_str1, base64_str2):
    if base64_str1 == None or base64_str2 == None:
        return False
    decoded_str1 = base64.b64decode(base64_str1)
    decoded_str2 = base64.b64decode(base64_str2)
    return decoded_str1 == decoded_str2

class GptBoy:
    def __init__(self, open_ai_key: str, rom_path: str = "pokemonred.gb", save_path: str = "gptboy.state",
                 debug: bool = False, sound: bool = True):
        # initialize gptboy params
        self.debug = debug

        # Initialize openai
        self.open_ai = OpenAI(api_key=open_ai_key)

        # Initialize state
        self.current_tick: int = 0
        self.running: bool = False
        self.requests = []
        self.upcoming_actions: list[str] = []
        self.previous_actions: list[str] = []

        # Initialize emulator
        self.save_path = save_path
        self.start_emulator(rom_path=rom_path, sound=sound)
        # self.tick(20)
        self.load_state()
        ppm = TICKS_PER_SECOND / PROMPT_N_SECONDS
        self.log(f"Starting GPTBOY! Running at a smooth {ppm} prompts per minute.")
        self.start()

    def tick(self, ticks: int = 1):
        for _tick in range(0, ticks):
            self.emulator.tick()
            self.current_tick += 1

    def load_state(self):
        with open(self.save_path, 'rb') as file:
            self.emulator.load_state(file)
    
    def save_state(self):
        with open(self.save_path, 'wb') as file:
            self.emulator.save_state(file)

    def start_emulator(self, rom_path: str, sound: bool):
        self.emulator = PyBoy(rom_path, sound=sound)

    def prune_requests(self):
        rstack_size = len(self.requests)
        self.requests = [request for request in self.requests if request.is_alive()]
        rstack_pruned = rstack_size - len(self.requests)
        self.log(f"Pruned \"{rstack_pruned}\" object(s) from Request Stack")
    def log(self, message: str):
        print(f"[{datetime.now()} TICK {self.current_tick}]: {message}")

    def repeated_actions(self):
        combined_text = ''.join(self.previous_actions)
        self.log(combined_text)
        # Count the occurrences of each letter
        letter_counts = collections.Counter(combined_text)
        # Filter the letters that have occurred more than 10 times
        filtered_letters = [letter for letter, count in letter_counts.items() if count > 10]
        return filtered_letters

    def press_button(self, button_text):
        if button_text in WINDOW_EVENTS:
            self.log(f"Pressing Button {button_text}")
            for b in range(0,2):
                self.emulator.send_input(WINDOW_EVENTS[button_text][b])
                self.tick(5)
            self.previous_actions.append(button_text)
            if len(self.previous_actions) >= 30:
                self.previous_actions.pop(0)
        else:
            # raise KeyError("Input {button_text} not found")
            print("ERROR Button not found: " + str(button_text))

    def prompt_gpt(self):
        encoded_image = image_to_bytes(self.emulator.screen_image())
        bad_actions = self.repeated_actions()
        actions_list = [x for x in ALL_ACTIONS if x not in bad_actions]
        try:
            self.log(f"Available actions {actions_list}")
            action_string = ", ".join(actions_list)
            response = self.open_ai.chat.completions.create(
                model="gpt-4-vision-preview",
                messages=[
                    {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"This is a screenshot of Pokemon: Red Version for the original gameboy. Return a single input based on the best next course of action based on the image. That input could be one of the following: {action_string}. DO NOT RESPOND WITH ANYTHING ELSE OR INPUT WILL BE DISCARDED. Attempt to respond with inputs as close to a human Pokemon player as possible. DO NOT WALK INTO WALLS. Use speedrunning TAS strategies when possible. When the keyboard is shown in an image, come up with a funny name. Always name pokemon. Only press A whenever a text box appears or a character is speaking, unless a selection appears."},
                        {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{encoded_image}",
                            "detail": "low"
                        },
                        },
                    ],
                    }
                ],
                max_tokens=2,
            )
            gpt_response_text = response.choices[0].message.content
            self.log("GPT Response: " + gpt_response_text)
            gpt_response_stripped = re.search("^\w+", gpt_response_text).group(0).upper()
            if gpt_response_stripped in WINDOW_EVENTS:
                self.upcoming_actions.append(gpt_response_stripped)
        except Exception as other_error:
            self.log(other_error)

    def start(self):
        self.running = True
        while self.running:
            if self.current_tick % TICKS_PER_MINUTE == 0:
                minutes = int(self.current_tick / TICKS_PER_MINUTE)
                self.log(f"Operational for {minutes} minute(s)")
            if self.current_tick % (ACTIONS_N_SECONDS * TICKS_PER_SECOND) == 0 \
                and len(self.upcoming_actions) != 0:
                current_action = self.upcoming_actions.pop(0)
                self.log(f"Popped \"{current_action}\" off Action Stack")
                self.press_button(current_action)
                self.save_state()
                self.prune_requests()
            if self.current_tick % (PROMPT_N_SECONDS * TICKS_PER_SECOND) == 0:
                rstack_size = len(self.requests)
                self.log("Running new request thread to OpenAI.")
                self.log(f"Rstack size {rstack_size}")
                new_request = threading.Thread(target=self.prompt_gpt)
                new_request.start()
                self.requests.append(new_request)
            if self.current_tick % (SAVE_N_SECONDS * TICKS_PER_SECOND) == 0 \
                and self.current_tick > SAVE_N_SECONDS * TICKS_PER_SECOND:
                self.save_state()
            self.tick()

if __name__ == "__main__":
    open_ai_key = os.environ.get("OPEN_AI_API_KEY", None)
    GptBoy(open_ai_key=open_ai_key, sound=False)
