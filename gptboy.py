import base64
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
PROMPT_N_SECONDS = 300
SAVE_N_SECONDS = 300

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

def image_to_bytes(image):
    jpeg_mafia = image.convert("RGB")
    buffered = BytesIO()
    jpeg_mafia.save(buffered, format="JPEG")
    image_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
    return image_str


class GptBoy:
    def __init__(self, open_ai_key: str, rom_path: str = "pokemonred.gb", save_path: str = "gptboy.state",
                 debug: bool = False, sound: bool = True):
        # initialize gptboy params
        self.debug = debug

        # Initialize openai
        self.open_ai = OpenAI(api_key=open_ai_key)

        # Initialize state
        self.current_tick = 0
        self.running = False
        self.requests = []
        self.actions: list[str] = []

        # Initialize emulator
        self.save_path = save_path
        self.start_emulator(rom_path=rom_path, sound=sound)
        # self.tick(20)
        self.load_state()
        ppm = TICKS_PER_MINUTE / PROMPT_N_SECONDS
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
        self.requests = [request for request in self.requests if request.is_alive()]

    def log(self, message: str):
        print(f"[{datetime.now()} TICK {self.current_tick}]: {message}")

    def press_button(self, button_text):
        if button_text in WINDOW_EVENTS:
            self.log(f"Pressing Button {button_text}")
            for b in range(0,2):
                self.emulator.send_input(WINDOW_EVENTS[button_text][b])
                self.tick(5)
        else:
            # raise KeyError("Input {button_text} not found")
            print("ERROR Button not found: " + str(button_text))

    def prompt_gpt(self):
        encoded_image = image_to_bytes(self.emulator.screen_image())
        try:
            response = self.open_ai.chat.completions.create(
                model="gpt-4-vision-preview",
                messages=[
                    {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "This is a screenshot of Pokemon: Red Version for the original gameboy. return a single input based on the best next course of action based on the image. That input could be one of the following: UP, DOWN, LEFT, RIGHT, A, B, START, SELECT. DO NOT RESPOND WITH ANYTHING ELSE OR INPUT WILL BE DISCARDED. Attempt to respond with inputs as close to a human Pokemon player as possible. When the keyboard is shown in an image, use the directional buttons to select characters, the A button to confirm them, and select END from the keyboard when completed."},
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
                self.actions.append(gpt_response_stripped)
        except Exception as other_error:
            self.log(other_error)

    def start(self):
        self.running = True
        while self.running:
            if self.current_tick % TICKS_PER_MINUTE == 0:
                minutes = int(self.current_tick / TICKS_PER_MINUTE)
                self.log(f"Operational for {minutes} minute(s)")
            if self.current_tick % (ACTIONS_N_SECONDS * TICKS_PER_SECOND) == 0 \
                and len(self.actions) != 0:
                self.log("Running check on action stack " + str(self.actions))
                action = self.actions.pop()
                self.press_button(action)
            if self.current_tick % (PROMPT_N_SECONDS * TICKS_PER_SECOND) == 0:
                self.log("Running new request thread")
                new_request = threading.Thread(target=self.prompt_gpt)
                new_request.start()
                self.requests.append(new_request)
            if self.current_tick % (SAVE_N_SECONDS * TICKS_PER_SECOND) == 0 \
                and self.current_tick > SAVE_N_SECONDS * TICKS_PER_SECOND:
                self.log("Running timed save")
                self.save_state()
            self.tick()

if __name__ == "__main__":
    open_ai_key = os.environ.get("OPEN_AI_API_KEY", None)
    GptBoy(open_ai_key=open_ai_key)
