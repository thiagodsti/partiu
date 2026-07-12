"""Third-party API integrations (Immich, aircraft data providers, the Ollama
LLM parser fallback) — kept separate from feature packages (trips, flights,
sync, ...), which call into these as clients rather than owning the API
integration logic themselves."""
