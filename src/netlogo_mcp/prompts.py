"""NetLogo MCP prompts — structured templates for common workflows."""

from __future__ import annotations

from fastmcp.prompts import Message

from .server import mcp


@mcp.prompt()
def analyze_model(model_name: str) -> list[Message]:
    """Step-by-step guide to understanding an existing NetLogo model.

    Args:
        model_name: Name of the .nlogo model file to analyze.
    """
    return [
        Message(
            role="user",
            content=(
                f"I want to understand the NetLogo model '{model_name}'. "
                "Please follow these steps:\n\n"
                f"1. Open the model using the open_model tool with '{model_name}'.\n"
                "2. Read the model source via the netlogo://models/{name} resource.\n"
                "3. Identify and list:\n"
                "   - Global variables and their purposes\n"
                "   - Breeds and their breed-specific variables\n"
                "   - The setup procedure — what initial state it creates\n"
                "   - The go procedure — what happens each tick\n"
                "   - Any notable sub-procedures\n"
                "4. Run the model: call 'setup', then run_simulation for 100 ticks "
                "with relevant reporters (agent counts, key metrics).\n"
                "5. Use export_view to show me what the model looks like.\n"
                "6. Summarize:\n"
                "   - What the model simulates\n"
                "   - Key dynamics and emergent behaviors\n"
                "   - Interesting parameters to experiment with\n"
            ),
        )
    ]


@mcp.prompt()
def create_abm(
    description: str,
    agents: str = "turtles",
    behaviors: str = "movement, interaction",
) -> list[Message]:
    """Template for building a new agent-based model from scratch.

    Args:
        description: What the model should simulate.
        agents: Types of agents to include (e.g. 'predators, prey').
        behaviors: Key behaviors agents should exhibit.
    """
    return [
        Message(
            role="user",
            content=(
                f"Build a NetLogo agent-based model with this specification:\n\n"
                f"**Description:** {description}\n"
                f"**Agent types:** {agents}\n"
                f"**Key behaviors:** {behaviors}\n\n"
                "Please follow these steps:\n\n"
                "1. First, read netlogo://docs/primitives and "
                "netlogo://docs/programming for reference.\n"
                "2. Design the model structure:\n"
                "   - Define breeds for each agent type\n"
                "   - Define breed-specific and global variables\n"
                "   - Plan the setup and go procedures\n"
                "3. Write the complete NetLogo code.\n"
                "4. Use create_model to load it.\n"
                "5. Run 'setup' to initialize.\n"
                "6. Use export_view to show the initial state.\n"
                "7. Run the simulation for 200 ticks with relevant reporters.\n"
                "8. Export the view again to show the evolved state.\n"
                "9. Summarize the model's behavior and suggest experiments.\n"
            ),
        )
    ]


@mcp.prompt()
def explore_comses(topic: str) -> list[Message]:
    """Search CoMSES Net for a topic, pick the best NetLogo match, open it
    safely, and run a short baseline simulation — without ever fabricating
    NetLogo commands.

    Args:
        topic: Free-text description of what you want to model
               (e.g. "rumor spreading", "predator-prey", "urban traffic").
    """
    return [
        Message(
            role="user",
            content=(
                f"Find an agent-based model matching '{topic}' on CoMSES Net "
                "and run a short baseline. Follow these rules exactly.\n\n"
                '1. Call `search_comses(query="' + topic + '")`. Pick a top '
                "match preferring peer-reviewed + NetLogo results when "
                "available, but show me other strong candidates too if there "
                "aren't enough NetLogo ones.\n"
                "2. Call `get_comses_model(identifier=<chosen UUID>)` and "
                "present: title, authors, license, description, and the "
                "`citation_text` — researchers always need this.\n"
                "3. Call `open_comses_model(identifier=<UUID>)`. **Capture "
                "`resolved_version` from the JSON response** and reuse it for "
                "every subsequent `read_comses_files` call. Never pass "
                '"latest" again in this flow — the version could change '
                "between calls and you'd inspect a different cache slot.\n"
                '4. If the model is NetLogo (status = "loaded_netlogo"):\n'
                "   a. Call `read_comses_files(identifier=<UUID>, "
                'version=<resolved_version>, extensions=[".nlogo", '
                '".nlogox"])` — always include BOTH extensions, since the '
                "archive may have picked a .nlogox variant.\n"
                "   b. Scan the source for `to <name>` procedure names and "
                "`to-report <name>` reporters. Do NOT assume `setup` / `go` "
                "exist — read what's actually defined.\n"
                "   c. **Stop-and-ask fallback:** if no procedure resembles "
                "setup/initialize/start, OR no candidate reporters exist, "
                "stop after loading and ask me which procedure to run. Do "
                "not force-run commands the model does not define.\n"
                '   d. Otherwise: call `command("<discovered setup>")`. If '
                "that call errors (model wants parameters, files, a "
                "different invocation order, etc.), **stop and ask me** — "
                "do NOT guess alternates. Otherwise call "
                "`run_simulation(ticks=100, reporters=[<discovered>])` then "
                "`export_view`.\n"
                "   e. Call `read_comses_files(identifier=<UUID>, "
                'version=<resolved_version>, extensions=[".md", ".txt"], '
                "max_total_bytes=50000)` to read the ODD / README and "
                "summarize what the model simulates.\n"
                "5. If the model is NOT NetLogo (status = "
                '"not_runnable_in_netlogo"):\n'
                "   a. Call `read_comses_files(identifier=<UUID>, "
                'version=<resolved_version>, extensions=[".md", ".txt"])` '
                "for the ODD doc.\n"
                "   b. State the language clearly, show the citation, "
                "summarize the ODD findings, and stop. Do NOT auto-translate "
                "to NetLogo. If I explicitly ask you to translate later, you "
                "may attempt it with the source — but be honest about "
                "simplifications.\n\n"
                "Be concise. Show tool results you act on, skip raw JSON I "
                "don't need."
            ),
        )
    ]


@mcp.prompt()
def parameter_sweep(
    parameter: str,
    min_val: float,
    max_val: float,
    steps: int = 5,
    metric: str = "count turtles",
) -> list[Message]:
    """Template for systematic parameter exploration.

    Args:
        parameter: Name of the global variable to sweep.
        min_val: Minimum value for the parameter.
        max_val: Maximum value for the parameter.
        steps: Number of values to test (evenly spaced).
        metric: NetLogo reporter to measure as the outcome.
    """
    step_size = (max_val - min_val) / max(steps - 1, 1)
    values = [round(min_val + i * step_size, 4) for i in range(steps)]
    values_str = ", ".join(str(v) for v in values)

    return [
        Message(
            role="user",
            content=(
                f"Run a parameter sweep on '{parameter}' to see how it affects "
                f"'{metric}'.\n\n"
                f"**Parameter:** {parameter}\n"
                f"**Values to test:** {values_str}\n"
                f"**Metric to measure:** {metric}\n"
                f"**Ticks per run:** 200\n\n"
                "For each value:\n"
                "1. Run 'setup' to reset the model.\n"
                f"2. Set {parameter} to the test value using set_parameter.\n"
                "3. Run the simulation for 200 ticks.\n"
                f"4. Record the final value of: {metric}\n\n"
                "After all runs:\n"
                "5. Present results in a table (parameter value vs final metric).\n"
                "6. Describe the relationship — linear, threshold, U-shaped, etc.\n"
                "7. Identify the parameter value that optimizes the metric.\n"
                "8. Suggest follow-up experiments.\n"
            ),
        )
    ]
