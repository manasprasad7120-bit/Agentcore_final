"""MiBuddy-style orchestrator services.

Contains all services for the MiBuddy-inspired features in the orchestrator:
- Intent classification (general_chat, web_search, image_generation, knowledge_base_search)
- Direct model chat (bypass agent graphs, call registry models directly)
- Web search (Google Gemini with Google Search grounding)
- Image generation (DALL-E, Azure DALL-E, Nano Banana)
- Knowledge base search (Azure AI Agent with company docs)
- Document Q&A (upload docs, RAG via Pinecone)
- Model capabilities detection (auto-detect from model name/provider)
"""
