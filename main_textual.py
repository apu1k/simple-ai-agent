"""
Textual entrypoint for simple-ai-agent.

Run locally as a Textual TUI:
    textual run main_textual.py

Serve for browser access, depending on your Textual version:
    textual serve --host 127.0.0.1 --port 8000 main_textual:app
"""

import os

# textual-serve sets TEXTUAL_LOG=textual.log in --dev mode. The live devtools
# console does not need that file, and Textual writes every event to it without
# rotation. Remove only the file sink while retaining TEXTUAL=debug,devtools.
os.environ.pop("TEXTUAL_LOG", None)

from runtime.textual_loop import create_textual_app


app = create_textual_app()


if __name__ == "__main__":
    app.run()
