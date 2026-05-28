import asyncio
from types import SimpleNamespace

import app.admin.telegram_admin as telegram_admin
from app.admin.telegram_admin import (
    CURRENT_DEALS_COOLDOWN_SECONDS,
    TelegramAdminBot,
    is_authorized_admin,
)
from app.config import Settings


def test_admin_permission_uses_configured_chat_id_only() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://u:p@localhost/db",
        telegram_admin_chat_id="12345",
    )

    assert is_authorized_admin(12345, settings)
    assert not is_authorized_admin(67890, settings)
    assert not is_authorized_admin(None, settings)


class FakeMessage:
    def __init__(self) -> None:
        self.replies: list[dict[str, object]] = []

    async def reply_text(self, text: str, **kwargs: object) -> None:
        self.replies.append({"text": text, **kwargs})


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    async def send_message(self, **kwargs: object) -> None:
        self.messages.append(kwargs)


class FakeReportService:
    def __init__(self) -> None:
        self.calls = 0

    def build_current_deals_text(self) -> str:
        self.calls += 1
        return "\U0001f54b Latest YYZ &#8594; JED Deals"


class FakeScanService:
    def __init__(self) -> None:
        self.all_calls = 0
        self.category_calls: list[str] = []

    def scan_all_categories(self, *, respect_pause: bool) -> None:
        self.all_calls += 1

    def scan_category(self, category: str, *, respect_pause: bool) -> None:
        self.category_calls.append(category)


class FakeCallbackQuery:
    def __init__(self) -> None:
        self.answers: list[str | None] = []

    async def answer(self, text: str | None = None) -> None:
        self.answers.append(text)


def make_bot(
    report_service: FakeReportService,
    scan_service: FakeScanService | None = None,
) -> TelegramAdminBot:
    return TelegramAdminBot(
        settings=Settings(
            database_url="postgresql+psycopg://u:p@localhost/db",
            telegram_admin_chat_id="12345",
        ),
        session_factory=SimpleNamespace(),
        scan_service=scan_service or FakeScanService(),
        report_service=report_service,
    )


def test_start_command_sends_public_welcome_with_current_deals_button() -> None:
    report_service = FakeReportService()
    bot = make_bot(report_service)
    message = FakeMessage()
    update = SimpleNamespace(effective_message=message)
    context = SimpleNamespace(args=[])

    asyncio.run(bot.start_command(update, context))
    asyncio.run(bot.start_command(update, context))

    assert report_service.calls == 0
    assert "Welcome to Umrah Flight Watch" in message.replies[0]["text"]
    assert "Welcome to Umrah Flight Watch" in message.replies[1]["text"]
    keyboard = message.replies[0]["reply_markup"].inline_keyboard
    assert keyboard[0][0].text == "Get Current Deals"
    assert keyboard[0][0].callback_data == "current_deals"


def test_start_payload_sends_current_deals_to_non_admin_user() -> None:
    report_service = FakeReportService()
    bot = make_bot(report_service)
    fake_context = SimpleNamespace(args=["current_deals"], bot=FakeBot())
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=67890),
        effective_message=FakeMessage(),
    )

    asyncio.run(bot.start_command(update, fake_context))

    assert report_service.calls == 1
    assert fake_context.bot.messages[0]["chat_id"] == 67890
    assert "Latest YYZ" in fake_context.bot.messages[0]["text"]
    assert fake_context.bot.messages[0]["parse_mode"] == "HTML"
    keyboard = fake_context.bot.messages[0]["reply_markup"].inline_keyboard
    assert keyboard[0][0].text == "Refresh Latest Deals"


def test_current_deals_command_sends_current_deals_to_non_admin_user() -> None:
    report_service = FakeReportService()
    bot = make_bot(report_service)
    fake_context = SimpleNamespace(args=[], bot=FakeBot())
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=67890),
        effective_message=FakeMessage(),
    )

    asyncio.run(bot.current_deals(update, fake_context))

    assert report_service.calls == 1
    assert fake_context.bot.messages[0]["chat_id"] == 67890


def test_current_deals_command_rate_limits_repeated_requests() -> None:
    report_service = FakeReportService()
    bot = make_bot(report_service)
    fake_context = SimpleNamespace(args=[], bot=FakeBot())
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=67890),
        effective_message=FakeMessage(),
    )

    asyncio.run(bot.current_deals(update, fake_context))
    asyncio.run(bot.current_deals(update, fake_context))

    assert report_service.calls == 1
    assert fake_context.bot.messages[1]["chat_id"] == 67890
    assert fake_context.bot.messages[1]["text"].startswith("Please wait ")


def test_current_deals_command_succeeds_after_cooldown() -> None:
    report_service = FakeReportService()
    bot = make_bot(report_service)
    fake_context = SimpleNamespace(args=[], bot=FakeBot())
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=67890),
        effective_message=FakeMessage(),
    )

    asyncio.run(bot.current_deals(update, fake_context))
    bot._current_deals_last_requested_at[67890] -= CURRENT_DEALS_COOLDOWN_SECONDS + 1
    asyncio.run(bot.current_deals(update, fake_context))

    assert report_service.calls == 2
    assert len(fake_context.bot.messages) == 2
    assert "Latest YYZ" in fake_context.bot.messages[1]["text"]


def test_current_deals_callback_answers_and_sends_new_message() -> None:
    report_service = FakeReportService()
    bot = make_bot(report_service)
    callback = FakeCallbackQuery()
    fake_context = SimpleNamespace(args=[], bot=FakeBot())
    update = SimpleNamespace(
        callback_query=callback,
        effective_chat=SimpleNamespace(id=67890),
        effective_message=None,
    )

    asyncio.run(bot.current_deals_callback(update, fake_context))

    assert callback.answers == [None]
    assert report_service.calls == 1
    assert fake_context.bot.messages[0]["chat_id"] == 67890


def test_current_deals_callback_rate_limits_repeated_requests() -> None:
    report_service = FakeReportService()
    bot = make_bot(report_service)
    callback = FakeCallbackQuery()
    fake_context = SimpleNamespace(args=[], bot=FakeBot())
    update = SimpleNamespace(
        callback_query=callback,
        effective_chat=SimpleNamespace(id=67890),
        effective_message=None,
    )

    asyncio.run(bot.current_deals_callback(update, fake_context))
    asyncio.run(bot.current_deals_callback(update, fake_context))

    assert report_service.calls == 1
    assert len(fake_context.bot.messages) == 1
    assert callback.answers[0] is None
    assert callback.answers[1].startswith("Please wait ")


def test_admin_commands_remain_admin_only_for_non_admin_user() -> None:
    report_service = FakeReportService()
    bot = make_bot(report_service)
    message = FakeMessage()
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=67890), effective_message=message)

    asyncio.run(bot.status(update, SimpleNamespace()))

    assert message.replies == [{"text": "Unauthorized."}]


def test_scan_now_runs_manual_scan_in_background(monkeypatch) -> None:
    async def scenario() -> None:
        report_service = FakeReportService()
        scan_service = FakeScanService()
        bot = make_bot(report_service, scan_service=scan_service)
        message = FakeMessage()
        fake_context = SimpleNamespace(args=["all"], bot=FakeBot())
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=12345),
            effective_message=message,
        )
        release_scan = asyncio.Event()

        async def fake_to_thread(func, *args, **kwargs):
            await release_scan.wait()
            return func(*args, **kwargs)

        monkeypatch.setattr(telegram_admin.asyncio, "to_thread", fake_to_thread)

        await bot.scan_now(update, fake_context)
        await asyncio.sleep(0)

        assert message.replies == [{"text": "Starting manual scan: all"}]
        assert fake_context.bot.messages == []
        assert bot._manual_scan_task is not None
        assert not bot._manual_scan_task.done()

        release_scan.set()
        await bot._manual_scan_task

        assert scan_service.all_calls == 1
        assert fake_context.bot.messages == [
            {"chat_id": 12345, "text": "Manual scan finished: all"}
        ]

    asyncio.run(scenario())


def test_scan_now_rejects_second_manual_scan_while_running(monkeypatch) -> None:
    async def scenario() -> None:
        report_service = FakeReportService()
        bot = make_bot(report_service, scan_service=FakeScanService())
        message = FakeMessage()
        fake_context = SimpleNamespace(args=["all"], bot=FakeBot())
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=12345),
            effective_message=message,
        )
        release_scan = asyncio.Event()

        async def fake_to_thread(func, *args, **kwargs):
            await release_scan.wait()
            return func(*args, **kwargs)

        monkeypatch.setattr(telegram_admin.asyncio, "to_thread", fake_to_thread)

        await bot.scan_now(update, fake_context)
        await asyncio.sleep(0)
        await bot.scan_now(update, fake_context)

        assert message.replies == [
            {"text": "Starting manual scan: all"},
            {"text": "Manual scan already running."},
        ]

        release_scan.set()
        if bot._manual_scan_task is not None:
            await bot._manual_scan_task

    asyncio.run(scenario())
