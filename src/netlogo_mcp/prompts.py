"""NetLogo MCP prompts — structured templates for common workflows."""

from __future__ import annotations

from fastmcp.prompts import Prompt, Message

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
