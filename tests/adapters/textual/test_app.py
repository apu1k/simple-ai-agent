import asyncio

from textual.app import App, ComposeResult
from textual.events import Paste

from adapters.textual.app import ClipboardInput


class ClipboardTestApp(App):
    def compose(self) -> ComposeResult:
        yield ClipboardInput(id="input")


def test_remote_paste_is_joined_and_inserted_at_cursor() -> None:
    async def run_test() -> None:
        app = ClipboardTestApp()
        async with app.run_test() as pilot:
            input_widget = app.query_one("#input", ClipboardInput)
            input_widget.value = "left right"
            input_widget.cursor_position = 4

            input_widget.on_paste(Paste("first  value\r\nsecond    value"))
            await pilot.pause()

            assert input_widget.value == "leftfirst  value second    value right"
            assert input_widget.cursor_position == len("leftfirst  value second    value")

    asyncio.run(run_test())


def test_long_first_paste_scrolls_to_the_cursor() -> None:
    async def run_test() -> None:
        app = ClipboardTestApp()
        async with app.run_test(size=(20, 8)) as pilot:
            input_widget = app.query_one("#input", ClipboardInput)
            input_widget.focus()
            pasted_text = "first\tline\n" + ("second\tline " * 10)
            expected = "first   line " + ("second  line " * 10)

            input_widget.post_message(Paste(pasted_text))
            await pilot.pause()

            assert input_widget.value == expected
            assert "\t" not in input_widget.value
            assert input_widget.cursor_position == len(input_widget.value)
            assert input_widget.scroll_x > 0
            assert input_widget.scroll_x == input_widget.max_scroll_x

            await pilot.press("X")
            await pilot.pause()

            assert input_widget.value.endswith("X")
            assert input_widget.cursor_position == len(input_widget.value)
            assert input_widget.scroll_x == input_widget.max_scroll_x
            assert input_widget.render_line(0).text.rstrip().endswith("X")

    asyncio.run(run_test())
