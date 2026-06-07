"""Application interface for type hints (generalized version)"""
from abc import ABC, abstractmethod
from collections.abc import Callable
import logging
from enum import Enum, auto
from typing import Any

logger = logging.getLogger(__name__)

from reusable_gui.core.events.event_dispatcher import EventDispatcher
from reusable_gui.core.config.settings_manager import BaseSettingsManager


class ApplicationState(Enum):
    """Defines the possible states of the application's lifecycle."""
    INITIALIZING = auto()
    READY = auto()
    RUNNING = auto()
    SHUTTING_DOWN = auto()
    CLOSED = auto()


class BaseApplication(ABC):
    """Interface definition for the main application."""

    def __init__(self) -> None:
        self._state = ApplicationState.INITIALIZING
        self._state_listeners: list[Callable[[ApplicationState], None]] = []

    @property
    def state(self) -> ApplicationState:
        """Gets the current state of the application."""
        return self._state

    def subscribe_to_state(self, callback: Callable[[ApplicationState], None]) -> None:
        """
        Registers a callback to be invoked when the application state changes.

        Args:
            callback: The function to call with the new state.
        """
        if callback not in self._state_listeners:
            self._state_listeners.append(callback)

    def _set_state(self, new_state: ApplicationState) -> None:
        """
        Updates the application state and notifies all registered listeners.

        Args:
            new_state: The new state to set.
        """
        if self._state != new_state:
            self._state = new_state
            for listener in self._state_listeners:
                try:
                    listener(new_state)
                except Exception as e:
                    logger.error(f"Error in state listener for state {new_state}: {e}", exc_info=True)

    @property
    @abstractmethod
    def translator(self) -> Any:
        """Translates language keys."""
        pass

    @property
    @abstractmethod
    def event_dispatcher(self) -> EventDispatcher:
        """Gets the application's event dispatcher."""
        pass

    @property
    @abstractmethod
    def settings_manager(self) -> BaseSettingsManager:
        """Gets the application's settings manager."""
        pass

    @property
    @abstractmethod
    def theme_manager(self) -> Any:
        """Gets the application's theme manager."""
        pass

    @abstractmethod
    def open_settings_window(self) -> None:
        """Opens the settings window."""
        pass

    @abstractmethod
    def on_ready(self) -> None:
        """Called when the application is fully initialized and ready to run."""
        pass

    @abstractmethod
    def on_closing(self) -> None:
        """Handles the main window closing event."""
        pass

    @abstractmethod
    def shutdown(self) -> None:
        """Performs a clean shutdown of the application."""
        pass
