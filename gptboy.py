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

INITIAL_PROMPT = "You are a superintelligent game playing program. I will send you an image of Pokemon: Red Version. Please respond with 2 lines of text. On line 1, describe what you see and where you believe you are, identify the next course of action that should be taken based on walkthroughs of Pokemon: Red Version. On line 2, return a list of inputs to press on the gameboy separated by a comma, up to 30 inputs. Use the inputs on line 2 to perform the action stated on line 1. The inputs could be one of the following AND ONLY THE FOLLOWING: Start, Select, A, B, Up, Down, Right, and Left. On line 2, DO NOT RESPOND WITH ANYTHING ELSE OR INPUT WILL BE DISCARDED. Valid inputs will be inserted into the game via a program. When you see a textbox, only press A once. When you see an option, always choose a custom name. When you see a keypad, name everything after Halo. On line 1, read all text in the screenshot. On line 1, describe every object you see in the game world and their location relative to the player character. YOU MUST use both lines or your input will be discarded. DO NOT PREFACE WITH \"INTENT\" OR \"INPUTS\" or \"ACTIONS\", \"Line 1:\" or \"Line 2:\""

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
    def __init__(self, open_ai_key: str, rom_path: str = "pokemonred.gb", game_title: str = "Pokemon: Red Version", save_path: str = "gptboy.state",
                 debug: bool = False, sound: bool = True):
        # initialize gptboy params
        self.debug = debug

        # Initialize openai
        self.open_ai = OpenAI(api_key=open_ai_key)

        # Initialize gptboy state
        self.current_tick: int = 0
        self.running: bool = False
        self.requests = []
        self.upcoming_actions: list[str] = []
        self.previous_actions: list[str] = []
        self.intents:list[str] = []
        self.gpt_messages: list[dict] = []
        self.speaking = False

        # Initialize emulator
        self.game_title = game_title
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

    def prompt_gpt_text(self, message):
        try:
            response = self.open_ai.chat.completions.create(
                model="gpt-4-1106-preview",
                messages=[{
                        "role": "user",
                        "content": message
                    }],
                max_tokens=200,
            )
            gpt_response_text = response.choices[0].message.content
            return gpt_response_text
        except Exception as other_error:
            self.log(other_error)            

    def prompt_gpt_image(self):
        encoded_image = image_to_bytes(self.emulator.screen_image())
        # bad_actions = self.repeated_actions()
        # actions_list = [x for x in ALL_ACTIONS if x not in bad_actions]
        actions_list = [x for x in ALL_ACTIONS]
        if len(self.gpt_messages) >= 10:
            self.gpt_messages.pop(1)
        try:    
            message = "Continue with your previous goal with a new intent and action. Learn from your mistakes and failures by comparing this image to the previous image. Update the intent accordingly and then use the intent to inform your actions. You are responsible for your own analysis, and ensuring the player character progresses through the game. Your assessment of objects isn't always accurate. "
            self.gpt_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{encoded_image}",
                                "detail": "auto"
                            },
                            },
                            {
                                "type": "text", 
                                "text": message
                            },
                        ],
                    }
                )
            if len(self.gpt_messages) >= 10:
                self.gpt_messages.pop(0)
            new_messages = self.gpt_messages
            new_messages.insert(0, {
                "role": "user",
                "content": [
                    {
                    "type": "text", 
                    "text": INITIAL_PROMPT
                    }
                ]
            })
            response = self.open_ai.chat.completions.create(
                model="gpt-4-vision-preview",
                messages=self.gpt_messages,
                max_tokens=3000,
            )
            gpt_response_text = response.choices[0].message.content
            self.log("GPT Response: " + gpt_response_text)
            gpt_intent, gpt_previous_actions = gpt_response_text.replace("\n\n", "\n").split("\n")[0:2]
            self.intents.append(gpt_intent)
            self.gpt_messages.append(
                    {
                        "role": "system",
                        "content": [
                            {
                                "type": "text", 
                                "text": gpt_response_text
                            },
                        ],
                    }
            )
            gpt_actions = gpt_previous_actions.split(",")
            for action in gpt_actions:
                action_stripped = action.replace(" ", "").upper()
                if action_stripped in actions_list:
                    self.upcoming_actions.append(action_stripped)
            self.save_context()
        except Exception as other_error:
            self.log(other_error)
            pokejoke = self.prompt_gpt_text("Write a very funny pokemon joke Heavily inspired by Norm MacDonald.")
            self.intents.append("Unfortunately it seems we have receieved an error code from ground control at Open AI, and the current action will be skipped. To lighten the mood, I have one of my famous PokéJokes to tell you all! " + pokejoke)

    def speak(self, text, ding=True):
        if ding:
            ding_dong = threading.Thread(target=playsound, args=("resources/audio/ding.mp3",))
            ding_dong.start()
        whisper_request = threading.Thread(target=self.speak_thread, args=(text,))
        whisper_request.start()

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
        self.speak(f"Welcome to GPT Boy. Speech module engaged. This is your captain speaking. Currently it is about {time.strftime('%l:%M%p %Z on %B %d, %Y')} as we are starting a generated playthrough of {self.game_title}. Current settings have us at about {PROMPT_N_SECONDS} seconds between prompting OpenAI for input. All responses, intents, and button presses will be dictated as they are processed. In addition, the current state will be saved every {SAVE_N_SECONDS} seconds. Whenever you hear the chime, a new input is about to begin. Are you ready to start?")
        while self.running:
            if self.speaking == False and len(self.intents) > 0:
                self.speak("This is your captain speaking. " + self.intents.pop(0))
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
            if self.current_tick % (PROMPT_N_SECONDS * TICKS_PER_SECOND) == 0 \
                and self.current_tick >= (30 * TICKS_PER_SECOND) \
                and self.speaking == False:
                rstack_size = len(self.requests)
                self.log("Running new request thread to OpenAI.")
                # self.log(f"Rstack size {rstack_size}")
                new_request = threading.Thread(target=self.prompt_gpt_image)
                new_request.start()
                self.requests.append(new_request)
            if self.current_tick % (SAVE_N_SECONDS * TICKS_PER_SECOND) == 0 \
                and self.current_tick > SAVE_N_SECONDS * TICKS_PER_SECOND:
                self.save_state()
            self.tick()

if __name__ == "__main__":
    open_ai_key = os.environ.get("OPEN_AI_API_KEY", None)
    GptBoy(open_ai_key=open_ai_key, rom_path="pokemonred.gb", sound=False)
