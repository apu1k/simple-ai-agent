"""
Textual entrypoint for simple-ai-agent.

Run locally as a Textual TUI:
    textual run main_textual.py

Serve for browser access, depending on your Textual version:
    textual serve --host 127.0.0.1 --port 8000 main_textual:app
"""

from runtime.textual_loop import create_textual_app


app = create_textual_app()


if __name__ == "__main__":
    app.run()
