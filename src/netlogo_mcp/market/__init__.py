"""SynthAudience — pre-flight marketing campaign testing.

Simulates an audience of persona-driven customers inside a NetLogo social
network. Persona *cognition* (how an individual reacts to an ad, email, or
landing page) is delegated to an LLM; the *social physics* (exposure timing,
word-of-mouth diffusion, fatigue, opinion drift) runs as classical ABM rules.

Modules
-------
- ``schemas``      Pydantic models: Persona, Stimulus, Reaction, specs.
- ``config``       Env-driven configuration (data dir, LLM endpoint).
- ``personas``     Audience generation from distribution specs.
- ``archetypes``   K-means clustering of personas for response caching.
- ``cognition``    LLM clients (live + mock), prompts, decision engine.
- ``stimulus``     Campaign artifact ingestion (YAML, pasted copy, HTML).
- ``netlogo_gen``  Generates the market_sim NetLogo model source.
- ``worlds``       WorldBridge implementations: NetLogo and pure-Python.
- ``orchestrator`` The tick loop: expose -> cognize -> write back -> go.
- ``store``        SQLite event store for runs/exposures/decisions.
- ``calibration``  Maps raw LLM propensities to real-world base rates.
- ``analytics``    Funnel, segment breakdown, objection mining, A/B stats.
- ``report``       Pre-flight report rendering (markdown + HTML).
- ``tools``        MCP tool surface (registered by the server).
"""
