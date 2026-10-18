"""Lost/Found intake wizards built on aiogram FSM."""
from datetime import date, datetime, timedelta
from html import escape

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from asgiref.sync import sync_to_async

from bot_app.models import TelegramUser
from catalog.models import Category, Color, Location
from reports.models import FoundReport, LostReport

from .keyboards import (
    areas_inline,
    buildings_inline,
    categories_inline,
    colors_inline,
    consent_inline,
    custody_inline,
    edit_steps_inline,
    main_menu,
    photo_inline,
    summary_inline,
)
from .states import FoundWizard, LostWizard
from .strings import t

router = Router()

DATE_FORMATS = ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y")
TITLE_MIN, TITLE_MAX = 3, 120
DESC_MIN, DESC_MAX = 5, 2000
NO_COMMAND_TEXT = ~F.text.startswith("/")


def parse_date(raw: str):
    cleaned = raw.strip()
    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
        if parsed > date.today() or parsed < date.today() - timedelta(days=3650):
            return None
        return parsed
    return None


async def fetch_categories():
    return await sync_to_async(list)(Category.objects.order_by("id"))


async def fetch_colors():
    return await sync_to_async(list)(Color.objects.order_by("id"))


async def fetch_buildings(lang: str):
    def collect():
        entries = []
        seen = set()
        for location in Location.objects.order_by("id"):
            if location.building_uz not in seen:
                seen.add(location.building_uz)
                entries.append((location.building_uz, location.localized_building(lang)))
        return entries
    return await sync_to_async(collect)()


async def fetch_areas(building: str):
    return await sync_to_async(list)(
        Location.objects.filter(building_uz=building).order_by("id")
    )


async def _advance(state: FSMContext, next_state) -> bool:
    """Returns True when the wizard is in edit mode and must jump to summary."""
    data = await state.get_data()
    if data.get("_editing"):
        await state.update_data(_editing=None)
        return True
    await state.set_state(next_state)
    return False


def _summary_lines(lang: str, data: dict, is_found: bool) -> str:
    lines = [
        t(lang, "w_summary_header"),
        "",
        f"🏷 {t(lang, 'f_category')}: {escape(str(data.get('category_label') or '—'))}",
        f"📝 {t(lang, 'f_title')}: {escape(str(data.get('title') or '—'))}",
        f"📄 {t(lang, 'f_description')}: {escape(str(data.get('description') or '—'))}",
        f"🎨 {t(lang, 'f_color')}: {escape(str(data.get('color_label') or '—'))}",
        f"📍 {t(lang, 'f_location')}: "
        + (escape(str(data.get("location_label"))) if data.get("location_id") else t(lang, "f_no_location")),
        f"📅 {t(lang, 'f_date')}: {data.get('date') or '—'}",
        f"🖼 {t(lang, 'f_photo')}: "
        + ("✅" if data.get("photo_file_id") else t(lang, "f_no_photo")),
    ]
    if is_found:
        custody = data.get("custody")
        custody_label = (
            t(lang, "c_handed_to_office") if custody == "handed_to_office" else t(lang, "c_kept_by_finder")
        )
        lines.append(f"🏛 {t(lang, 'f_custody')}: {custody_label}")
        lines.append(
            f"🔗 {t(lang, 'f_consent')}: " + (t(lang, "f_yes") if data.get("consent") else t(lang, "f_no"))
        )
    return "\n".join(lines)


# Display-only labels captured at pick time can be stale if the user
# switches language mid-wizard; refresh them from stored IDs before
# showing the summary so everything renders in the current language.
async def _refresh_labels(lang: str, state: FSMContext) -> None:
    data = await state.get_data()
    updates: dict = {}

    category_id = data.get("category_id")
    if category_id:
        category = await sync_to_async(Category.objects.get)(pk=category_id)
        updates["category_label"] = f"{category.emoji} {category.localized_name(lang)}"

    color_id = data.get("color_id")
    if color_id:
        color = await sync_to_async(Color.objects.get)(pk=color_id)
        updates["color_label"] = color.localized_name(lang)

    location_id = data.get("location_id")
    if location_id:
        location = await sync_to_async(Location.objects.get)(pk=location_id)
        updates["location_label"] = location.display(lang)
        updates["building_label"] = location.localized_building(lang)
    elif data.get("building"):
        updates["building_label"] = await _building_label(lang, data["building"])

    if updates:
        await state.update_data(**updates)


def _fetch_building_label(lang: str, building_key: str) -> str:
    location = Location.objects.filter(building_uz=building_key).first()
    return location.localized_building(lang) if location else building_key


async def _building_label(lang: str, building_key: str) -> str:
    return await sync_to_async(_fetch_building_label)(lang, building_key)


async def _show_summary(message: Message, state: FSMContext, lang: str, is_found: bool):
    wizard = FoundWizard if is_found else LostWizard
    await state.set_state(wizard.summary)
    await _refresh_labels(lang, state)
    data = await state.get_data()
    await message.answer(
        _summary_lines(lang, data, is_found),
        reply_markup=summary_inline(lang),
    )


async def _prompt(message: Message, state: FSMContext, lang: str, field: str, is_found: bool):
    await _refresh_labels(lang, state)
    data = await state.get_data()
    current = {
        "category": data.get("category_label"),
        "title": data.get("title"),
        "description": data.get("description"),
        "color": data.get("color_label"),
        "building": data.get("building_label"),
        "date": data.get("date"),
    }
    header = ""
    if data.get("_editing") and current.get(field if field != "location" else "building"):
        header = t(lang, "w_current").format(value=str(current.get(field if field != "location" else "building"))) + "\n\n"

    if field == "category":
        await message.answer(
            f"{header}{t(lang, 'prompt_category')}",
            reply_markup=categories_inline(lang, await fetch_categories()),
        )
    elif field == "title":
        await message.answer(f"{header}{t(lang, 'prompt_title')}")
    elif field == "description":
        await message.answer(f"{header}{t(lang, 'prompt_description')}")
    elif field == "color":
        await message.answer(
            f"{header}{t(lang, 'prompt_color')}",
            reply_markup=colors_inline(lang, await fetch_colors()),
        )
    elif field == "building" or field == "location":
        await message.answer(
            f"{header}{t(lang, 'prompt_building')}",
            reply_markup=buildings_inline(lang, await fetch_buildings(lang)),
        )
    elif field == "date":
        key = "prompt_date_found" if is_found else "prompt_date_lost"
        await message.answer(f"{header}{t(lang, key)}")
    elif field == "photo":
        await message.answer(f"{header}{t(lang, 'prompt_photo')}", reply_markup=photo_inline(lang))
    elif field == "custody":
        await message.answer(f"{header}{t(lang, 'prompt_custody')}", reply_markup=custody_inline(lang))
    elif field == "consent":
        await message.answer(f"{header}{t(lang, 'prompt_consent')}", reply_markup=consent_inline(lang))


async def _start_wizard(message: Message, state: FSMContext, django_user: TelegramUser, is_found: bool):
    await state.clear()
    wizard = FoundWizard if is_found else LostWizard
    await state.set_state(wizard.category)
    lang = django_user.language
    header_key = "w_found_header" if is_found else "w_lost_header"
    await message.answer(t(lang, header_key))
    await _prompt(message, state, lang, "category", is_found)


@router.message(F.text.startswith("🧳"))
async def start_lost_wizard(message: Message, state: FSMContext, django_user: TelegramUser):
    await _start_wizard(message, state, django_user, is_found=False)


@router.message(F.text.startswith("🎁"))
async def start_found_wizard(message: Message, state: FSMContext, django_user: TelegramUser):
    await _start_wizard(message, state, django_user, is_found=True)


@router.callback_query(StateFilter(LostWizard, FoundWizard), F.data == "wiz_cancel")
async def wizard_cancel(call: CallbackQuery, state: FSMContext, django_user: TelegramUser):
    await state.clear()
    if call.message is not None:
        await call.message.answer(t(django_user.language, "w_cancelled"), reply_markup=main_menu(django_user.language))
    await call.answer()


async def _pick_category(call: CallbackQuery, state: FSMContext, lang: str, is_found: bool):
    category_id = int(call.data.split(":", 1)[1])
    category = await sync_to_async(Category.objects.get)(pk=category_id)
    await state.update_data(
        category_id=category.id, category_label=f"{category.emoji} {category.localized_name(lang)}"
    )
    if await _advance(state, (FoundWizard if is_found else LostWizard).title):
        await _show_summary(call.message, state, lang, is_found)
    else:
        await _prompt(call.message, state, lang, "title", is_found)
    await call.answer()


@router.callback_query(LostWizard.category, F.data.startswith("setcat:"))
async def lost_pick_category(call: CallbackQuery, state: FSMContext, django_user: TelegramUser):
    await _pick_category(call, state, django_user.language, is_found=False)


@router.callback_query(FoundWizard.category, F.data.startswith("setcat:"))
async def found_pick_category(call: CallbackQuery, state: FSMContext, django_user: TelegramUser):
    await _pick_category(call, state, django_user.language, is_found=True)


async def _save_title(message: Message, state: FSMContext, lang: str, is_found: bool):
    title = (message.text or "").strip()
    if not (TITLE_MIN <= len(title) <= TITLE_MAX):
        await message.answer(t(lang, "w_invalid_title"))
        return
    await state.update_data(title=title)
    if await _advance(state, (FoundWizard if is_found else LostWizard).description):
        await _show_summary(message, state, lang, is_found)
    else:
        await _prompt(message, state, lang, "description", is_found)


@router.message(LostWizard.title, F.text & NO_COMMAND_TEXT)
async def lost_save_title(message: Message, state: FSMContext, django_user: TelegramUser):
    await _save_title(message, state, django_user.language, is_found=False)


@router.message(FoundWizard.title, F.text & NO_COMMAND_TEXT)
async def found_save_title(message: Message, state: FSMContext, django_user: TelegramUser):
    await _save_title(message, state, django_user.language, is_found=True)


async def _save_description(message: Message, state: FSMContext, lang: str, is_found: bool):
    description = (message.text or "").strip()
    if not (DESC_MIN <= len(description) <= DESC_MAX):
        await message.answer(t(lang, "w_invalid_description"))
        return
    await state.update_data(description=description)
    if await _advance(state, (FoundWizard if is_found else LostWizard).color):
        await _show_summary(message, state, lang, is_found)
    else:
        await _prompt(message, state, lang, "color", is_found)


@router.message(LostWizard.description, F.text & NO_COMMAND_TEXT)
async def lost_save_description(message: Message, state: FSMContext, django_user: TelegramUser):
    await _save_description(message, state, django_user.language, is_found=False)


@router.message(FoundWizard.description, F.text & NO_COMMAND_TEXT)
async def found_save_description(message: Message, state: FSMContext, django_user: TelegramUser):
    await _save_description(message, state, django_user.language, is_found=True)


async def _pick_color(call: CallbackQuery, state: FSMContext, lang: str, is_found: bool):
    color_id = int(call.data.split(":", 1)[1])
    color = await sync_to_async(Color.objects.get)(pk=color_id)
    await state.update_data(color_id=color.id, color_label=color.localized_name(lang))
    if await _advance(state, (FoundWizard if is_found else LostWizard).building):
        await _show_summary(call.message, state, lang, is_found)
    else:
        await _prompt(call.message, state, lang, "building", is_found)
    await call.answer()


@router.callback_query(LostWizard.color, F.data.startswith("setcol:"))
async def lost_pick_color(call: CallbackQuery, state: FSMContext, django_user: TelegramUser):
    await _pick_color(call, state, django_user.language, is_found=False)


@router.callback_query(FoundWizard.color, F.data.startswith("setcol:"))
async def found_pick_color(call: CallbackQuery, state: FSMContext, django_user: TelegramUser):
    await _pick_color(call, state, django_user.language, is_found=True)


async def _pick_building(call: CallbackQuery, state: FSMContext, lang: str, is_found: bool):
    index = int(call.data.split(":", 1)[1])
    building_entries = await fetch_buildings(lang)
    building_key, building_display = building_entries[index]
    await state.update_data(
        building=building_key,
        building_label=building_display,
        location_id=None,
        location_label=None,
    )
    wizard = FoundWizard if is_found else LostWizard
    data = await state.get_data()
    if data.get("_editing") == "location":
        await state.set_state(wizard.area)
        locations = await fetch_areas(building_key)
        await call.message.answer(
            t(lang, "prompt_area"),
            reply_markup=areas_inline(lang, locations, optional=not is_found),
        )
        await call.answer()
        return
    if await _advance(state, wizard.area):
        await _show_summary(call.message, state, lang, is_found)
    else:
        locations = await fetch_areas(building_key)
        await call.message.answer(
            t(lang, "prompt_area"),
            reply_markup=areas_inline(lang, locations, optional=not is_found),
        )
    await call.answer()


@router.callback_query(LostWizard.building, F.data.startswith("setbld:"))
async def lost_pick_building(call: CallbackQuery, state: FSMContext, django_user: TelegramUser):
    await _pick_building(call, state, django_user.language, is_found=False)


@router.callback_query(FoundWizard.building, F.data.startswith("setbld:"))
async def found_pick_building(call: CallbackQuery, state: FSMContext, django_user: TelegramUser):
    await _pick_building(call, state, django_user.language, is_found=True)


async def _pick_area(call: CallbackQuery, state: FSMContext, lang: str, is_found: bool):
    location_id = int(call.data.split(":", 1)[1])
    if location_id == 0:
        await state.update_data(location_id=None, location_label=None)
    else:
        location = await sync_to_async(Location.objects.get)(pk=location_id)
        await state.update_data(
            location_id=location.id, location_label=location.display(lang)
        )
    wizard = FoundWizard if is_found else LostWizard
    if await _advance(state, wizard.date):
        await _show_summary(call.message, state, lang, is_found)
    else:
        key = "prompt_date_found" if is_found else "prompt_date_lost"
        await call.message.answer(t(lang, key))
    await call.answer()


@router.callback_query(LostWizard.area, F.data.startswith("setarea:"))
async def lost_pick_area(call: CallbackQuery, state: FSMContext, django_user: TelegramUser):
    await _pick_area(call, state, django_user.language, is_found=False)


@router.callback_query(FoundWizard.area, F.data.startswith("setarea:"))
async def found_pick_area(call: CallbackQuery, state: FSMContext, django_user: TelegramUser):
    await _pick_area(call, state, django_user.language, is_found=True)


async def _save_date(message: Message, state: FSMContext, lang: str, is_found: bool):
    parsed = parse_date(message.text or "")
    if parsed is None:
        await message.answer(t(lang, "w_invalid_date"))
        return
    await state.update_data(date=parsed.isoformat())
    wizard = FoundWizard if is_found else LostWizard
    if await _advance(state, wizard.photo):
        await _show_summary(message, state, lang, is_found)
    else:
        await _prompt(message, state, lang, "photo", is_found)


@router.message(LostWizard.date, F.text & NO_COMMAND_TEXT)
async def lost_save_date(message: Message, state: FSMContext, django_user: TelegramUser):
    await _save_date(message, state, django_user.language, is_found=False)


@router.message(FoundWizard.date, F.text & NO_COMMAND_TEXT)
async def found_save_date(message: Message, state: FSMContext, django_user: TelegramUser):
    await _save_date(message, state, django_user.language, is_found=True)


async def _skip_photo(call: CallbackQuery, state: FSMContext, lang: str, is_found: bool):
    await state.update_data(photo_file_id=None)
    wizard = FoundWizard if is_found else LostWizard
    if await _advance(state, wizard.custody if is_found else wizard.summary):
        await _show_summary(call.message, state, lang, is_found)
    elif is_found:
        await _prompt(call.message, state, lang, "custody", is_found)
    else:
        await _show_summary(call.message, state, lang, is_found)
    await call.answer()


@router.callback_query(LostWizard.photo, F.data == "skippic")
async def lost_skip_photo(call: CallbackQuery, state: FSMContext, django_user: TelegramUser):
    await _skip_photo(call, state, django_user.language, is_found=False)


@router.callback_query(FoundWizard.photo, F.data == "skippic")
async def found_skip_photo(call: CallbackQuery, state: FSMContext, django_user: TelegramUser):
    await _skip_photo(call, state, django_user.language, is_found=True)


async def _save_photo(message: Message, state: FSMContext, lang: str, is_found: bool):
    photo_file_id = message.photo[-1].file_id if message.photo else None
    await state.update_data(photo_file_id=photo_file_id)
    wizard = FoundWizard if is_found else LostWizard
    data = await state.get_data()
    if data.get("_editing"):
        await _show_summary(message, state, lang, is_found)
        return
    if is_found:
        await state.set_state(FoundWizard.custody)
        await _prompt(message, state, lang, "custody", is_found)
    else:
        await _show_summary(message, state, lang, is_found)


@router.message(LostWizard.photo, F.photo)
async def lost_save_photo(message: Message, state: FSMContext, django_user: TelegramUser):
    await _save_photo(message, state, django_user.language, is_found=False)


@router.message(FoundWizard.photo, F.photo)
async def found_save_photo(message: Message, state: FSMContext, django_user: TelegramUser):
    await _save_photo(message, state, django_user.language, is_found=True)


@router.message(StateFilter(LostWizard.photo, FoundWizard.photo), F.text & NO_COMMAND_TEXT)
async def photo_invalid_text(message: Message, state: FSMContext, django_user: TelegramUser):
    await message.answer(t(django_user.language, "w_need_photo"))


@router.callback_query(FoundWizard.custody, F.data.startswith("custody:"))
async def found_pick_custody(call: CallbackQuery, state: FSMContext, django_user: TelegramUser):
    custody = call.data.split(":", 1)[1]
    await state.update_data(custody=custody)
    if await _advance(state, FoundWizard.consent):
        await _show_summary(call.message, state, django_user.language, is_found=True)
    else:
        await _prompt(call.message, state, django_user.language, "consent", is_found=True)
    await call.answer()


@router.callback_query(FoundWizard.consent, F.data.startswith("consent:"))
async def found_pick_consent(call: CallbackQuery, state: FSMContext, django_user: TelegramUser):
    consent = call.data.split(":", 1)[1] == "yes"
    await state.update_data(consent=consent)
    if await _advance(state, FoundWizard.summary):
        pass
    await _show_summary(call.message, state, django_user.language, is_found=True)
    await call.answer()


@router.callback_query(StateFilter(LostWizard.summary, FoundWizard.summary), F.data == "wiz_edit")
async def wizard_edit_menu(call: CallbackQuery, state: FSMContext, django_user: TelegramUser):
    current_state = await state.get_state()
    is_found = current_state is not None and current_state.startswith(FoundWizard.__name__)
    await call.message.answer(
        t(django_user.language, "w_edit_prompt"),
        reply_markup=edit_steps_inline(django_user.language, is_found),
    )
    await call.answer()


@router.callback_query(StateFilter(LostWizard.summary, FoundWizard.summary), F.data.startswith("editf:"))
async def wizard_edit_field(call: CallbackQuery, state: FSMContext, django_user: TelegramUser):
    field = call.data.split(":", 1)[1]
    current_state = await state.get_state()
    is_found = current_state is not None and current_state.startswith(FoundWizard.__name__)
    wizard = FoundWizard if is_found else LostWizard
    field_to_state = {
        "category": wizard.category,
        "title": wizard.title,
        "description": wizard.description,
        "color": wizard.color,
        "location": wizard.building,
        "date": wizard.date,
        "photo": wizard.photo,
    }
    if field in ("custody", "consent"):
        if not is_found:
            await call.answer()
            return
        field_to_state["custody"] = wizard.custody
        field_to_state["consent"] = wizard.consent
    await state.update_data(_editing=field)
    await state.set_state(field_to_state[field])
    await _prompt(call.message, state, django_user.language, field, is_found)
    await call.answer()


@router.callback_query(LostWizard.summary, F.data == "wiz_confirm")
async def lost_confirm(call: CallbackQuery, state: FSMContext, django_user: TelegramUser):
    data = await state.get_data()
    lang = django_user.language
    if not all(data.get(key) is not None for key in ("category_id", "title", "description", "color_id", "date")):
        await call.answer(t(lang, "w_invalid_choice"), show_alert=True)
        return

    def create():
        return LostReport.objects.create(
            reporter=django_user,
            category_id=data["category_id"],
            title=data["title"],
            description=data["description"],
            color_id=data["color_id"],
            location_id=data.get("location_id"),
            date_lost=data["date"],
            photo_file_id=data.get("photo_file_id") or "",
            status="open",
        )

    report = await sync_to_async(create)()
    await state.clear()
    await call.message.answer(
        t(lang, "w_created_lost").format(id=report.id),
        reply_markup=main_menu(lang),
    )
    await call.answer()


@router.callback_query(FoundWizard.summary, F.data == "wiz_confirm")
async def found_confirm(call: CallbackQuery, state: FSMContext, django_user: TelegramUser):
    data = await state.get_data()
    lang = django_user.language
    required = ("category_id", "title", "description", "color_id", "location_id", "date", "custody")
    if not all(data.get(key) is not None for key in required):
        await call.answer(t(lang, "w_invalid_choice"), show_alert=True)
        return

    def create():
        return FoundReport.objects.create(
            reporter=django_user,
            category_id=data["category_id"],
            title=data["title"],
            description=data["description"],
            color_id=data["color_id"],
            location_id=data["location_id"],
            date_found=data["date"],
            photo_file_id=data.get("photo_file_id") or "",
            custody=data["custody"],
            finder_contact_allowed=bool(data.get("consent")),
            status="open",
        )

    report = await sync_to_async(create)()
    await state.clear()
    await call.message.answer(
        t(lang, "w_created_found").format(id=report.id),
        reply_markup=main_menu(lang),
    )
    await call.answer()


# ---------------------------------------------------------------------------
# Mid-wizard language switching (option A: keep data, change only language)
# ---------------------------------------------------------------------------

_WIZARD_FIELDS = (
    "category", "title", "description", "color", "building", "area",
    "date", "photo", "custody", "consent", "summary",
)


async def _locate_wizard_state(state: FSMContext):
    """Map the active FSM state string to (is_found, field); None outside wizards."""
    current = await state.get_state()
    if not current:
        return None
    for is_found, group in ((False, LostWizard), (True, FoundWizard)):
        for field in _WIZARD_FIELDS:
            if f"{group.__name__}:{field}" == current:
                return is_found, field
    return None


async def resume_after_language_change(message: Message, state: FSMContext, lang: str) -> bool:
    """Keep all entered data and re-render the current wizard step in the
    freshly chosen language (already typed texts are NOT re-asked)."""
    info = await _locate_wizard_state(state)
    if info is None:
        return False
    is_found, field = info
    if field == "summary":
        await _show_summary(message, state, lang, is_found)
        return True
    if field == "area":
        data = await state.get_data()
        building_key = data.get("building")
        if not building_key:
            await state.set_state((FoundWizard if is_found else LostWizard).building)
            await _prompt(message, state, lang, "building", is_found)
            return True
        locations = await fetch_areas(building_key)
        await message.answer(
            t(lang, "prompt_area"),
            reply_markup=areas_inline(lang, locations, optional=not is_found),
        )
        return True
    wizard = FoundWizard if is_found else LostWizard
    await state.set_state(getattr(wizard, field))
    await _prompt(message, state, lang, field, is_found)
    return True


