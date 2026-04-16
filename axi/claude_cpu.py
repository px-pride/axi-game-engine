import asyncio
from concurrent.futures import ThreadPoolExecutor

from axi.abstract_cpu import AbstractCPU

try:
    from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, TextBlock
    CLAUDE_SDK_AVAILABLE = True
except ImportError:
    CLAUDE_SDK_AVAILABLE = False

PHASE_COMBAT = 0
PHASE_EFFECTS = 1

EMOJI_REFRESH = "\N{ANTICLOCKWISE DOWNWARDS AND UPWARDS OPEN CIRCLE ARROWS}"
EMOJI_SHIELD = "\N{SHIELD}"
EMOJI_CYCLONE = "\N{CYCLONE}"
EMOJI_NO_ENTRY = "\N{NO ENTRY SIGN}"
EMOJI_SKIP = "\N{BLACK RIGHT-POINTING DOUBLE TRIANGLE}"

SYSTEM_PROMPT = """You are an AI opponent in Wonder Wand, a tactical spell-casting card game.

RULES SUMMARY:
- Each player has 40 HP and a wand with 9 spells (3 classes x 6 elements).
- Each round, both players simultaneously choose: Cast a spell, Block, or Refresh.
- Spell classes: Counters (circles, defensive, reusable), Strikes (squares, high damage, consumable), Hexes (hearts, lingering effects, unblockable).
- Counters beat other classes on element ties. Strikes beat Hexes on ties. Hexes bypass blocks.
- Blocking a Counter/Strike lets you Bounce (return it, lock it out) or Cancel (remove it, costs 4 HP).
- Refreshing unprepares current spells, loads up to 5 new ones, and clears opponent hexes.
- Strikes/Hexes beat Refreshes. Counters do nothing against non-spells.
- Losing combat grants Divination: identify 2 of opponent's unrevealed spells.

ELEMENT MATCHUPS (row beats column with checkmark):
       Red  Org  Yel  Grn  Blu  Pur
Red:    =    L    =    W    L    =
Org:    W    =    W    L    L    L
Yel:    =    L    =    L    W    W
Grn:    L    W    W    =    W    L
Blu:    W    W    L    L    =    =
Pur:    =    W    L    W    =    =

STRATEGY TIPS:
- Track which opponent spells are revealed vs unknown.
- Refresh when your spell pool is empty or to clear hexes.
- Block when you expect a Strike or Counter (not a Hex).
- Use Hexes when opponent might block or refresh.
- Cancel expensive opponent spells; Bounce cheap ones.
- Consider element matchups when choosing which spell to cast.

You must respond with ONLY the emoji(s) for your chosen action(s), separated by spaces.
No explanation, no text — just the emoji(s)."""


class ClaudeCPU(AbstractCPU):
    def __init__(self, match):
        super().__init__(match)
        self.name = "Claude CPU"
        if not CLAUDE_SDK_AVAILABLE:
            raise ImportError(
                "claude-agent-sdk is required for ClaudeCPU. "
                "Install with: pip install claude-agent-sdk"
            )

    def compute(self, options):
        num_decisions = self.match.expected_num_decisions[self]
        prompt = self._build_prompt(options, num_decisions)

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, self._async_compute(prompt))
            response_text = future.result(timeout=60)

        return self._parse_response(response_text, options, num_decisions)

    async def _async_compute(self, prompt):
        response_text = ""
        sdk_options = ClaudeAgentOptions(
            system_prompt=SYSTEM_PROMPT,
            max_turns=1,
            model="claude-haiku-4-5",
            allowed_tools=[],
            max_budget_usd=0.01,
        )

        async for message in query(prompt=prompt, options=sdk_options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        response_text += block.text

        return response_text

    def _build_prompt(self, options, num_decisions):
        match = self.match
        state_msg = match.match_state(self)

        phase_name = "Combat" if match.phase == PHASE_COMBAT else "Effects"
        phase_context = self._phase_context()

        option_lines = []
        for emoji in options:
            desc = self._describe_option(emoji)
            option_lines.append(f"  {emoji} — {desc}")

        return (
            f"Round {match.round} — {phase_name} Phase\n"
            f"{phase_context}\n"
            f"Game State:\n{state_msg}\n"
            f"Available actions (choose {num_decisions}):\n"
            f"{chr(10).join(option_lines)}\n\n"
            f"Respond with {num_decisions} emoji(s), space-separated."
        )

    def _phase_context(self):
        match = self.match
        if match.phase == PHASE_COMBAT:
            return "Choose one action: cast a spell, block, or refresh."
        if self in match.casters:
            spell = match.wands[self].spells[match.combat_options[self]]
            return f"Your {spell.name} won combat. Make choices for its effect."
        if self in match.blockers:
            opp = match.opponent(self)
            opp_spell = match.wands[opp].spells[match.combat_options[opp]]
            return f"You blocked {opp_spell.name}. Choose: Bounce or Cancel."
        if self in match.chargers:
            return "You are refreshing your wand. Choose spells to prepare."
        if self in match.scouters:
            return "You lost combat. Choose spells to divine (reveal info about opponent)."
        return ""

    def _describe_option(self, emoji):
        match = self.match
        if emoji == EMOJI_REFRESH:
            return "Refresh — unprepare current spells, load new ones, clear hexes"
        if emoji == EMOJI_SHIELD:
            return "Block — defend against opponent's Counter or Strike"
        if emoji == EMOJI_CYCLONE:
            return "Bounce — return blocked spell to opponent, lock it out 1 round"
        if emoji == EMOJI_NO_ENTRY:
            return "Cancel — remove blocked spell permanently (costs you 4 HP)"
        if emoji == EMOJI_SKIP:
            return "Skip — no action needed"
        if emoji in match.emojis_to_moves:
            color, shape_name = match.emojis_to_moves[emoji]
            if emoji in match.wands[self].spells:
                spell = match.wands[self].spells[emoji]
                return f"Cast {spell.name} ({color} {shape_name}). {spell.description()}"
            # During refresh/divination, describe the color-shape
            return f"Select {color} {shape_name} spell"
        return "Unknown action"

    def _parse_response(self, text, options, num_decisions):
        text = text.strip()

        # Find emojis from options that appear in the response
        chosen = []
        for emoji in options:
            if emoji in text and emoji not in chosen:
                chosen.append(emoji)
                if len(chosen) >= num_decisions:
                    break

        # Fallback: if parsing failed, pick first available option(s)
        if not chosen:
            chosen = options[:num_decisions]

        if num_decisions == 1:
            return chosen[0]
        return chosen[:num_decisions]
