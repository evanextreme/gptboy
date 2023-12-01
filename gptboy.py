import base64
import collections
from datetime import datetime
import json
import math
import re
import threading
from io import BytesIO
import time
from openai import OpenAI
from pyboy import WindowEvent
from pyboy import PyBoy
import os
from playsound import playsound

TICKS_PER_SECOND = 60
TICKS_PER_MINUTE = math.pow(TICKS_PER_SECOND,2)
ACTIONS_N_SECONDS = 2
PROMPT_N_SECONDS = 60
SAVE_N_SECONDS = 300
REGENERATION_MODE_MULTIPLE = 5

WINDOW_EVENTS = {
    "START": (WindowEvent.PRESS_BUTTON_START, WindowEvent.RELEASE_BUTTON_START),
    "SELECT": (WindowEvent.PRESS_BUTTON_SELECT, WindowEvent.RELEASE_BUTTON_SELECT),
    "A": (WindowEvent.PRESS_BUTTON_A, WindowEvent.RELEASE_BUTTON_A),
    "B": (WindowEvent.PRESS_BUTTON_B, WindowEvent.RELEASE_BUTTON_B),
    "UP": (WindowEvent.PRESS_ARROW_UP, WindowEvent.RELEASE_ARROW_UP),
    "DOWN": (WindowEvent.PRESS_ARROW_DOWN, WindowEvent.RELEASE_ARROW_DOWN),
    "LEFT": (WindowEvent.PRESS_ARROW_LEFT, WindowEvent.RELEASE_ARROW_LEFT),
    "RIGHT": (WindowEvent.PRESS_ARROW_RIGHT, WindowEvent.RELEASE_ARROW_RIGHT),
}

ALL_ACTIONS = list(WINDOW_EVENTS.keys())

INITIAL_PROMPT = f"These are two images of of Pokemon: Crystal Version. Upon showing you the first image, I asked to provide the next step for the game, and a list of button inputs on the next line. You responded The first image shows the  Use 2 lines of text. On line 1, describe what you see and where you believe you are, identify the next course of action that should be taken based on walkthroughs of Pokemon: Crystal Version. On line 2, return a list of inputs to press on the gameboy separated by a comma, up to 30 inputs. Use the inputs on line 2 to perform the action stated on line 1. The inputs could be one of the following AND ONLY THE FOLLOWING: {ALL_ACTIONS}. On line 2, DO NOT RESPOND WITH ANYTHING ELSE OR INPUT WILL BE DISCARDED. DO NOT PREFACE WITH \"INTENT\" OR \"INPUTS\" or \"ACTIONS\". When you see a textbox, only press A once. On line 1, read all text in the screenshot. On line 1, describe every object you see in the game world and their location relative to the player character. YOU MUST use both lines or your input will be discarded."

def image_to_bytes(image):
    jpeg_mafia = image.convert("RGB")
    buffered = BytesIO()
    jpeg_mafia.save(buffered, format="JPEG")
    jpeg_mafia.save("testimage.jpg")
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
        self.intents:list[str] = []
        self.gpt_messages: list[dict] = []
        self.speaking = False

        # Initialize emulator
        self.save_path = save_path
        self.load_context()
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
        if os.path.exists(self.save_path):
            with open(self.save_path, 'rb') as file:
                self.emulator.load_state(file)
    
    def save_state(self):
        with open(self.save_path, 'wb') as file:
            self.emulator.save_state(file)

    def load_context(self):
        if os.path.exists("data.json"):
            with open("data.json", "r") as file:
                json_data = file.read()
                self.gpt_messages = json.loads(json_data)

    def save_context(self):
        json_data = json.dumps(self.gpt_messages)

        # Save the JSON data to a file
        with open("data.json", "w") as file:
            file.write(json_data)

    def start_emulator(self, rom_path: str, sound: bool):
        self.emulator = PyBoy(rom_path, sound=sound)

    def prune_requests(self):
        rstack_size = len(self.requests)
        self.requests = [request for request in self.requests if request.is_alive()]
        rstack_pruned = rstack_size - len(self.requests)
        # self.log(f"Pruned \"{rstack_pruned}\" object(s) from Request Stack")

    def log(self, message: str):
        print(f"[{datetime.now()} TICK {self.current_tick}]: {message}")

    def repeated_actions(self):
        action_counter = {}
        filtered_actions = []
        for action in self.previous_actions:
            if action in action_counter:
                action_counter[action] += 1
            else:
                action_counter[action] = 1
        for action, count in action_counter.items():
            if count >= 20:
                filtered_actions.append(action)
        self.log(action_counter)
        self.log(filtered_actions)
        return filtered_actions

    def press_button(self, button_text):
        if button_text in WINDOW_EVENTS:
            self.log(f"Pressing Button {button_text}")
            audio_filename = "resources/audio/" + button_text.lower() + ".mp3"
            button_speaker = threading.Thread(target=playsound, args=(audio_filename,))
            button_speaker.start()
            for b in range(0,2):
                self.emulator.send_input(WINDOW_EVENTS[button_text][b])
                self.tick(10)
            self.previous_actions.append(button_text)
            if len(self.previous_actions) >= 40:
                self.previous_actions.pop(0)
        else:
            # raise KeyError("Input {button_text} not found")
            print("ERROR Button not found: " + str(button_text))

    def prompt_gpt(self):
        pil_image = self.emulator.screen_image()
        encoded_image = image_to_bytes(self.emulator.screen_image())
        # bad_actions = self.repeated_actions()
        # actions_list = [x for x in ALL_ACTIONS if x not in bad_actions]
        actions_list = [x for x in ALL_ACTIONS]

        try:
            message = "With the context of the previous actions and images, re adjust your goal and approach to continue playing the game with the same method. Learn from your mistakes and failures, and analyze why what you did either worked or didnt in the Intent section. Then use the Intent to inform your Actions. In the intent, describe whether the previous step functioned as intended. Did the screen change? If not, try something else. For instance, if you believed going downstairs was to the left, and that didnt work, then that assumption was wrong. Ensure you are doing through analysis of your decisions and whether they work. Get out of the bedroom by going to the top right"
            if len(self.gpt_messages) < 1:
                message = INITIAL_PROMPT
            self.gpt_messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{encoded_image}",
                            "detail": "low"
                        },
                        },
                        {
                            "type": "text", 
                            "text": message
                        },
                    ],
                }
            )
            response = self.open_ai.chat.completions.create(
                model="gpt-4-vision-preview",
                messages=self.gpt_messages,
                max_tokens=3000,
            )
            self.log(self.gpt_messages)
            self.gpt_response_text = response.choices[0].message.content
            self.log("GPT Response: " + self.gpt_response_text)
            gpt_intent, gpt_previous_actions = self.gpt_response_text.replace("\n\n", "\n").split("\n")[0:2]
            self.intents.append(gpt_intent)
            gpt_actions = gpt_previous_actions.split(",")
            self.log(gpt_actions)
            for action in gpt_actions:
                action_stripped = action.replace(" ", "")
                if action_stripped in actions_list:
                    self.upcoming_actions.append(action_stripped)
            self.save_context()
        except Exception as other_error:
            self.log(other_error)

    def speak(self, text):
        new_request = threading.Thread(target=self.speak_thread, args=(text,))
        new_request.start()

    def speak_thread(self, text, buffer_file=None):
        while self.speaking == True:
            time.sleep(5)
        self.speaking = True
        filename = threading.current_thread().name + ".mp3"
        if buffer_file != None:
            filename = buffer_file
        response = self.open_ai.audio.speech.create(
            model="tts-1",
            voice="alloy",
            input=text)
        response.stream_to_file(filename)
        playsound(filename)
        if buffer_file == None:
            os.remove(filename)
        self.speaking = False

    def start(self):
        self.running = True
        while self.running:
            if self.speaking == False and len(self.intents) > 0:
                self.speak(self.intents.pop(0))
            if self.current_tick % TICKS_PER_MINUTE == 0:
                minutes = int(self.current_tick / TICKS_PER_MINUTE)
                self.log(f"Operational for {minutes} minute(s)")
            if self.current_tick % (ACTIONS_N_SECONDS * TICKS_PER_SECOND) == 0 \
                and len(self.upcoming_actions) != 0 and self.speaking == False:
                current_action = self.upcoming_actions.pop(0)
                # self.log(f"Popped \"{current_action}\" off Action Stack")
                self.press_button(current_action)
                self.save_state()
                self.prune_requests()
            if self.current_tick % (PROMPT_N_SECONDS * TICKS_PER_SECOND) == 0 and self.current_tick >= (30 * TICKS_PER_SECOND):
                rstack_size = len(self.requests)
                self.log("Running new request thread to OpenAI.")
                # self.log(f"Rstack size {rstack_size}")
                new_request = threading.Thread(target=self.prompt_gpt)
                new_request.start()
                self.requests.append(new_request)
            if self.current_tick % (SAVE_N_SECONDS * TICKS_PER_SECOND) == 0 \
                and self.current_tick > SAVE_N_SECONDS * TICKS_PER_SECOND:
                self.save_state()
            self.tick()

if __name__ == "__main__":
    open_ai_key = os.environ.get("OPEN_AI_API_KEY", None)
    GptBoy(open_ai_key=open_ai_key, rom_path="pokemoncrystal.gbc", sound=False)
