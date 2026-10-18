"""FSM states for the lost/found intake wizards."""
from aiogram.fsm.state import State, StatesGroup


class LostWizard(StatesGroup):
    category = State()
    title = State()
    description = State()
    color = State()
    building = State()
    area = State()
    date = State()
    photo = State()
    summary = State()


class FoundWizard(StatesGroup):
    category = State()
    title = State()
    description = State()
    color = State()
    building = State()
    area = State()
    date = State()
    photo = State()
    custody = State()
    consent = State()
    summary = State()
