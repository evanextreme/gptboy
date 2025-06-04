# gptboy

This is a project I started working on in late 2023 as an interesting experiment during an on call rotation week which did not fully pan out (was planning to launch twitch.tv/gptplayspokemon). At the time, GPT-4 Vision was the only language model with visual input capabilities, and it was limiting in a few ways. First, the costs of the model were astronomical and it would cost me thousands a month to operate the stream continuously, even with the input batching I later implemented. Token context was also an issue, as this utilized older API's that did not hold on to previous context. Second, and more importantly, the actual "world knowledge" of the model was limited. It was shockingly capable of understanding the images being sent to it, such as where the player character was and the next objective they need to achieve, but was incapable of understanding the inputs to achieve that objective (It would constantly try to leave the bedroom by going down, because most exits are on the bottom). The goal was then to impelement it into a Twitch chat, and use the language model more like a "dungeon master" that would respect inputs from the chat after filtering them through a second prompt. In retrospect, both Anthropic and Google have announced their own projects where they have had their respective models complete Pokemon Blue. They were able to overcome both of these struggles with both improved models, and the ability to bankroll these costs due to their ownership of the compute. The project isn't necessarily "abandoned" yet, I plan to improve the agnosticism of models and games to allow companies to use it as a benchmark for LLM progress.

## Installation

1. Ensure you have Python installed (tested with Python 3).
2. Install the project dependencies:

```bash
pip install -r requirements.txt
```

3. Set your OpenAI API key as an environment variable:

```bash
export OPEN_AI_API_KEY="your-api-key"
```

4. Execute the main program:

```bash
python gptboy.py
```

The script expects a Game Boy ROM named `pokemonsilver.gbc` in the same directory.
