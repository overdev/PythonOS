'''
Created on Dec 27, 2015

@author: Adam Furman
@copyright: Open Source
'''
import pygame
import json
import os
import __builtin__
from importlib import import_module
from shutil import rmtree
from zipfile import ZipFile
from thread import start_new_thread
from datetime import datetime
from __builtin__ import staticmethod
from traceback import format_exc

# state = None
screen = None

DEFAULT = 0xada


def read_file(path):
    # type: (str) -> list
    f = open(path, "rU")
    lines = []
    for line in f.readlines():
        lines.append(line.rstrip())
    f.close()
    return lines


class Thread(object):
    def __init__(self, method, **data):
        # type: (Callable, dict) -> None
        self.event_bindings = {}                                            # type: Dict[str, Callable[...]]
        self.pause = False                                                  # type: bool
        self.stop = False                                                   # type: bool
        self.first_run = True                                               # type: bool
        self.method = method                                                # type: Callable[...]
        self.pause = data.get("startPaused", False)
        self.event_bindings["onStart"] = data.get("onStart", None)
        self.event_bindings["onStop"] = data.get("onStop", None)
        self.event_bindings["onPause"] = data.get("onPause", None)
        self.event_bindings["onResume"] = data.get("onResume", None)
        self.event_bindings["onCustom"] = data.get("onCustom", None)

    @staticmethod
    def __default_evt_method(self, *args):
        # type: (Tuple[...]) -> None
        return

    def exec_event(self, evt_key, *params):
        # type: (str, Tuple[...]) -> None
        to_exec = self.event_bindings.get(evt_key, Thread.__default_evt_method)
        if to_exec is None:
            return
        if isinstance(to_exec, list):
            to_exec[0](*to_exec[1])
        else:
            to_exec(*params)

    def set_pause(self, state="toggle"):
        # type: (Union[str, bool]) -> None
        if isinstance(state, bool):
            self.pause = not self.pause
        else:
            self.pause = state
        if self.pause:
            self.exec_event("onPause")
        else:
            self.exec_event("onResume")

    def set_stop(self):
        # type: () -> None
        self.stop = True
        self.exec_event("onStop")

    def run(self):
        # type: () -> None
        try:
            if self.first_run:
                if self.event_bindings["onStart"] is not None:
                    self.exec_event("onStart")
                self.first_run = False
            if not self.pause and not self.stop:
                self.method()
        except:
            State.error_recovery("Thread error.", "Thread bindings: " + str(self.event_bindings))
            self.stop = True
            self.first_run = False


class Task(Thread):
    def __init__(self, method, *additional_data):
        # type: (Callable, Tuple[...]) -> None
        super(Task, self).__init__(method)
        self.returned_data = None                           # type: Any
        self.additional_data = additional_data              # type: Tuple[...]

    def run(self):
        # type: () -> None
        self.returned_data = self.method(*self.additional_data)
        self.set_stop()

    def get_return(self):
        # type: () -> Any
        return self.returned_data

    def set_pause(self, state="toggle"):
        # type: () -> None
        return

    def exec_event(self, evt_key, *params):
        # type: () -> None
        return


class StagedTask(Task):
    def __init__(self, method, max_stage=10):
        super(StagedTask, self).__init__(method)
        self.stage = 1                      # type: int
        self.max_stage = max_stage          # type: int

    def run(self):
        # type: () -> None
        self.returned_data = self.method(self.stage)
        self.stage += 1
        if self.stage >= self.max_stage:
            self.set_stop()


class TimedTask(Task):
    def __init__(self, execute_on, method, *additional_data):
        # type: (datetime.time, Tuple[...]) -> None
        self.execution_time = execute_on
        super(TimedTask, self).__init__(method, *additional_data)

    def run(self):
        # type: () -> None
        delta = self.execution_time - datetime.now()            # type: datetime.delta
        if delta.total_seconds() <= 0:
            super(TimedTask, self).run()


class ParallelTask(Task):
    # Warning: This starts a new thread.
    def __init__(self, method, *additional_data):
        # type: (Callable, Tuple[...]) -> None
        super(ParallelTask, self).__init__(method, *additional_data)
        self.ran = False                                                    # type: bool

    def run(self):
        # type: () -> None
        if not self.ran:
            start_new_thread(self.run_helper, ())
            self.ran = True

    def get_return(self):
        # type: () -> None
        return None

    def run_helper(self):
        # type: () -> None
        self.method(*self.additional_data)
        self.set_stop()

    def set_stop(self):
        # type: () -> None
        super(ParallelTask, self).set_stop()


class Controller(object):
    def __init__(self):
        # type: () -> None
        self.threads = []                   # type: List[Union[Thread, Task, StagedTask, TimedTask, ParalelTask]]
        self.data_requests = {}             # type: dict

    def request_data(self, from_thread, default=None):
        # type: (Thread, Optional[Any]) -> None
        self.data_requests[from_thread] = default

    def get_requested_data(self, from_thread):
        # type: (Union[Thread, Task, StagedTask, TimedTask, ParalelTask]) -> Any
        return self.data_requests[from_thread]

    def add_thread(self, thread):
        # type: (Union[Thread, Task, StagedTask, TimedTask, ParalelTask]) -> None
        self.threads.append(thread)

    def remove_thread(self, thread):
        try:
            if isinstance(thread, int):
                self.threads.pop(thread)
            else:
                self.threads.remove(thread)
        except:
            print
            "Thread was not removed!"

    def stop_all_threads(self):
        # type: () -> None
        for thread in self.threads:
            thread.set_stop()

    def run(self):
        # type: () -> None
        for thread in self.threads:
            thread.run()
            if thread in self.data_requests:
                try:
                    self.data_requests[thread] = thread.get_return()
                except:
                    self.data_requests[thread] = False  # get_return called on Thread, not Task
            if thread.stop:
                self.threads.remove(thread)


class GUI(object):
    def __init__(self):
        # type: () -> None
        global screen
        # 0 for portrait, 1 for landscape
        self.orientation = 0                        # type: int
        self.timer = None                           # type: pygame.time.Clock
        self.update_interval = 30                   # type: int
        pygame.init()
        if __import__("sys").platform == "linux2":
            info = pygame.display.Info()
            self.width = info.current_w             # type: int
            self.height = info.current_h            # type: int
            screen = pygame.display.set_mode((info.current_w, info.current_h))
        else:
            screen = pygame.display.set_mode((240, 320), pygame.HWACCEL)
            self.width = screen.get_width()         # type: int
            self.height = screen.get_height()       # type: int
        try:
            screen.blit(pygame.image.load("res/splash2.png"), [0, 0])
        except:
            screen.blit(pygame.font.Font(None, 20).render("Loading Python OS 6...", 1, (200, 200, 200)), [5, 5])
        pygame.display.flip()
        __builtin__.screen = screen
        globals()["screen"] = screen
        self.timer = pygame.time.Clock()
        pygame.display.set_caption("PyOS 6")

    def orient(self, orientation):
        # type: (int) -> None
        global screen
        if orientation != self.orientation:
            self.orientation = orientation
            if orientation == 0:
                self.width = 240
                self.height = 320
            if orientation == 1:
                self.width = 320
                self.height = 240
            screen = pygame.display.set_mode((self.width, self.height))

    def repaint(self):
        # type: () -> None
        screen.fill(state.get_color_palette().get_color("background"))

    def refresh(self):
        # type: () -> None
        pygame.display.flip()

    def get_screen(self):
        # type: () -> pygame.Surface
        return screen

    def monitor_fps(self):
        # type: () -> None
        real = round(self.timer.get_fps())
        if real >= self.update_interval and self.update_interval < 30:
            self.update_interval += 1
        else:
            if self.update_interval > 10:
                self.update_interval -= 1

    def display_standby_text(self, text="Stand by...", size=20, color=(20, 20, 20), bgcolor=(100, 100, 200)):
        # type: (Optional[str], Optional[int], Optional[Tuple[int, int, int]], Optional[Tuple[int, int, int]]) -> None
        pygame.draw.rect(screen, bgcolor,
                         [0, ((state.get_gui().height - 40) / 2) - size, state.get_gui().width, 2 * size])
        screen.blit(state.get_font().get(size).render(text, 1, color),
                    (5, ((state.get_gui().height - 40) / 2) - size + (size / 4)))
        pygame.display.flip()

    @staticmethod
    def get_centered_coordinates(component, larger):
        # type: (Any, Any) -> Tuple[int, int]
        return [(larger.width / 2) - (component.width / 2), (larger.height / 2) - (component.height / 2)]

    class Font(object):
        def __init__(self, path="res/RobotoCondensed-Regular.ttf", min_size=10, max_size=30):
            # type: (Optional[str], Optional[int], Optional[int]) -> None
            self.path = path                    # type: str
            self.sizes = {}                     # type: Dict[int, pygame.font.Font]
            curr_size = min_size
            while curr_size <= max_size:
                self.sizes[curr_size] = pygame.font.Font(path, curr_size)
                curr_size += 1

        def get(self, size=14):
            # type: (Optional[int]) -> pygame.font.Font
            if size in self.sizes:
                return self.sizes[size]
            return pygame.font.Font(self.path, size)

    class Icons(object):
        def __init__(self):
            self.root_path = "res/icons/"
            self.icons = {
                "menu": "menu.png",
                "unknown": "unknown.png",
                "error": "error.png",
                "warning": "warning.png",
                "file": "file.png",
                "folder": "folder.png",
                "wifi": "wifi.png",
                "python": "python.png",
                "quit": "quit.png",
                "copy": "files_copy.png",
                "delete": "files_delete.png",
                "goto": "files_goto.png",
                "home_dir": "files_home.png",
                "move": "files_move.png",
                "select": "files_select.png",
                "up": "files_up.png",
                "back": "back.png",
                "forward": "forward.png",
                "search": "search.png",
                "info": "info.png",
                "open": "open.png",
                "save": "save.png"
            }

        def get_icons(self):
            # type: () -> None
            return self.icons

        def get_root_path(self):
            # type: () -> str
            return self.root_path

        def get_loaded_icon(self, icon, folder=""):
            # type: (str, Optional[str]) -> pygame.Surface
            try:
                return pygame.image.load(os.path.join(self.root_path, self.icons[icon]))
            except:
                if os.path.exists(icon):
                    return pygame.transform.scale(pygame.image.load(icon), (40, 40))
                if os.path.exists(os.path.join("res/icons/", icon)):
                    return pygame.transform.scale(pygame.image.load(os.path.join("res/icons/", icon)), (40, 40))
                if os.path.exists(os.path.join(folder, icon)):
                    return pygame.transform.scale(pygame.image.load(os.path.join(folder, icon)), (40, 40))
                return pygame.image.load(os.path.join(self.root_path, self.icons["unknown"]))

        @staticmethod
        def load_from_file(path):
            # type: (str) -> GUI.Icons
            f = open(path, "rU")
            icondata = json.load(f)
            toreturn = GUI.Icons()
            for key in dict(icondata).keys():
                toreturn.icons[key] = icondata.get(key)
            f.close()
            return toreturn

    class ColorPalette(object):
        def __init__(self):
            # type: () -> None
            self.palette = {
                "normal": {
                    "background": (200, 200, 200),
                    "item": (20, 20, 20),
                    "accent": (100, 100, 200),
                    "warning": (250, 160, 45),
                    "error": (250, 50, 50)
                },
                "dark": {
                    "background": (50, 50, 50),
                    "item": (220, 220, 220),
                    "accent": (50, 50, 150),
                    "warning": (200, 110, 0),
                    "error": (200, 0, 0)
                },
                "light": {
                    "background": (250, 250, 250),
                    "item": (50, 50, 50),
                    "accent": (150, 150, 250),
                    "warning": (250, 210, 95),
                    "error": (250, 100, 100)
                }
            }                                       # type: Dict[str, Dict[str, Tuple[int, int, int]]]
            self.scheme = "normal"                  # type: str

        def get_palette(self):
            # type: () -> Dict[str, Dict[str, Tuple[int, int, int]]]
            return self.palette

        def get_scheme(self):
            # type: () -> str
            return self.scheme

        def color_add(self, c, d):
            return (c[0] + d[0], c[1] + d[1], c[2] + d[2])

        def get_color(self, item):
            # type: (str) -> Tuple[int, int, int]
            if item.find(":") == -1:
                return self.palette[self.scheme][item]
            else:
                split = item.split(":")
                if split[0] == "darker":
                    return max(self.color_add(self.get_color(split[1]), (-20, -20, -20)), (0, 0, 0))
                if split[0] == "dark":
                    return max(self.color_add(self.get_color(split[1]), (-40, -40, -40)), (0, 0, 0))
                if split[0] == "lighter":
                    return min(self.color_add(self.get_color(split[1]), (20, 20, 20)), (250, 250, 250))
                if split[0] == "light":
                    return min(self.color_add(self.get_color(split[1]), (40, 40, 40)), (250, 250, 250))
                if split[0] == "transparent":
                    return self.get_color(split[1]) + (int(split[2].rstrip("%")) / 100,)

        def __getitem__(self, item):
            # type: (str) -> Tuple[int, int, int]
            return self.get_color(item)

        def set_scheme(self, scheme="normal"):
            # type: (Optional[str]) -> None
            self.scheme = scheme

        @staticmethod
        def load_from_file(path):
            # type: (str) -> GUI.ColorPalette
            f = open(path, "rU")
            colordata = json.load(f)
            toreturn = GUI.ColorPalette()
            for key in dict(colordata).keys():
                toreturn.palette[key] = colordata.get(key)
            f.close()
            return toreturn

        @staticmethod
        def html_to_rgb(colorstring):
            # type: (str) -> Tuple[int, int, int]
            colorstring = colorstring.strip()
            if colorstring[0] == '#':
                colorstring = colorstring[1:]
            if len(colorstring) != 6:
                raise ValueError("input #%s is not in #RRGGBB format" % colorstring)
            r, g, b = colorstring[:2], colorstring[2:4], colorstring[4:]
            r, g, b = [int(n, 16) for n in (r, g, b)]
            return (r, g, b)

        @staticmethod
        def rgb_to_html_color(rgb_tuple):
            # type: (Tuple[int, int, int]) -> str
            hexcolor = '#%02x%02x%02x' % rgb_tuple
            return hexcolor

    class LongClickEvent(object):
        def __init__(self, mouse_down):
            self.mouse_down = mouse_down                # type: pygame.event.Event
            self.mouse_down_time = datetime.now()       # type: datetime
            self.mouse_up = None                        # type: pygema.event.Event
            self.mouse_up_time = None                   # type: datetime
            self.intermediate_points = []               # type: List[Tuple[int, int], ...]
            self.pos = self.mouse_down.pos              # type: Tuple[int, int]

        def intermediate_update(self, mouse_move):
            # type: (pygame.event.Event) -> None
            if self.mouse_up is None:
                self.intermediate_points.append(mouse_move.pos)

        def end(self, mouse_up):
            # type: (pygame.event.Event) -> None
            self.mouse_up = mouse_up
            self.mouse_up_time = datetime.now()
            self.pos = self.mouse_up.pos

        def get_latest_update(self):
            if len(self.intermediate_points) == 0:
                return self.pos
            else:
                return self.intermediate_points[-1]

        def check_valid_long_click(self, time=300):
            # type: (Optional[int]) -> None
            """Checks timestamps against parameter (in milliseconds)"""
            delta = self.mouse_up_time - self.mouse_down_time
            return (delta.microseconds / 1000) >= time

    class IntermediateUpdateEvent(object):
        def __init__(self, pos, src):
            # type: (Tuple[int, int], pygame.event.Event) -> None
            self.pos = pos                  # type: Tuple[int, int]
            self.sourceEvent = src          # type: pygame.event.Event

    class EventQueue(object):
        def __init__(self):
            # type: () -> None
            self.events = []            # type: List[GUI.LongClickEvent]

        def check(self):
            # type: () -> None
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    State.exit()
                if event.type == pygame.MOUSEBUTTONDOWN:
                    self.events.append(GUI.LongClickEvent(event))
                if (event.type == pygame.MOUSEMOTION and len(self.events) > 0 and
                        isinstance(self.events[-1], GUI.LongClickEvent)):
                    self.events[-1].intermediate_update(event)
                if (event.type == pygame.MOUSEBUTTONUP and len(self.events) > 0 and
                        isinstance(self.events[-1], GUI.LongClickEvent)):
                    self.events[-1].end(event)
                    if not self.events[-1].check_valid_long_click():
                        self.events[-1] = self.events[-1].mouse_up

        def get_latest(self):
            # type: () -> GUI.LongClickEvent
            if len(self.events) == 0:
                return None
            return self.events.pop()

        def remove_event(self, ev):
            # type: (GUI.LongClickEvent) -> None
            if ev in self.events:
                self.events.remove(ev)

        def get_latest_complete(self):
            if len(self.events) == 0:
                return None
            p = len(self.events) - 1
            while p >= 0:
                event = self.events[p]
                if isinstance(event, GUI.LongClickEvent):
                    if event.mouse_up is not None:
                        return self.events.pop(p)
                    else:
                        try:
                            return GUI.IntermediateUpdateEvent(self.events[-1].get_latest_update(),
                                                               self.events[-1])
                        except AttributeError:
                            print self.events[-1]
                            print self.events
                            sys.exit(1)
                else:
                    return self.events.pop(p)
                p -= 1

        def clear(self):
            del self.events[:]

    class Component(object):
        def __init__(self, position, **data):
            # type: (Tuple[int, int]) -> None
            self.position = list(position)[:]           # type: List[int, int]
            self.width = -1                             # type: int
            self.height = -1                            # type: int
            self.event_bindings = {}                    # type: Dict[str, Callable]
            self.event_data = {}                        # type: Dict[str, Any]
            self.data = data                            # type: Tuple[...]
            self.surface = None                         # type: pygame.Surface
            self.border = 0                             # type: int
            self.border_color = (0, 0, 0)               # type: Tuple[int, int, int]
            self.original_paramters = {
                "position": position[:],
                "width": data.get("width", data["surface"].get_width() if data.get("surface", False) else 0),
                "height": data.get("height", data["surface"].get_height() if data.get("surface", False) else 0)
            }                                           # type: Dict[str, Any]
            if "surface" in data:
                self.surface = data["surface"]
                if "width" in data or "height" in data:
                    if "width" in data:
                        if type(data["width"]) == str and data["width"].endswith("%"):
                            self.width = int(
                                (state.get_active_application().ui.width / 100) * int(data["width"].replace("%", "")))
                        else:
                            self.width = data["width"]
                        if "height" not in data:
                            self.height = self.surface.get_height()
                    if "height" in data:
                        if type(data["height"]) == str and data["height"].endswith("%"):
                            self.height = int(
                                (state.get_active_application().ui.height / 100) * int(data["height"].replace("%", "")))
                        else:
                            self.height = data["height"]
                        if self.width == -1:
                            self.width = self.surface.get_width()
                    self.surface = pygame.transform.scale(self.surface, (self.width, self.height))
                else:
                    self.width = self.surface.get_width()
                    self.height = self.surface.get_height()
            else:
                if "width" in data and type(data["width"]) == str and data["width"].endswith("%"):
                    self.width = int(
                        (state.get_active_application().ui.width / 100.0) * int(data["width"].replace("%", "")))
                else:
                    self.width = data.get("width", 0)
                if "height" in data and type(data["height"]) == str and data["height"].endswith("%"):
                    self.height = int(
                        (state.get_active_application().ui.height / 100.0) * int(data["height"].replace("%", "")))
                else:
                    self.height = data.get("height", 0)
                self.surface = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
            if type(self.position[0]) == str and self.position[0].endswith("%"):
                self.position[0] = int(
                    (state.get_active_application().ui.width / 100.0) * int(self.position[0].replace("%", "")))
            if type(self.position[1]) == str and self.position[1].endswith("%"):
                self.position[1] = int(
                    (state.get_active_application().ui.height / 100.0) * int(self.position[1].replace("%", "")))
            self.event_bindings["onClick"] = data.get("onClick", None)
            self.event_bindings["onLongClick"] = data.get("onLongClick", None)
            self.event_bindings["onIntermediateUpdate"] = data.get("onIntermediateUpdate", None)
            self.event_data["onClick"] = data.get("onClickData", None)
            self.event_data["onIntermediateUpdate"] = data.get("onIntermediateUpdateData", None)
            self.event_data["onLongClick"] = data.get("onLongClickData", None)
            if "border" in data:
                self.border = int(data["border"])
                self.border_color = data.get("border_color", state.get_color_palette().get_color("item"))
            self.inner_click_coordinates = (-1, -1)                 # type: Tuple[int, int]
            self.inner_offset = [0, 0]                              # type: Tuple[int, int]
            self.internal_click_overrides = {}                      # type: Dict[str, Callable[]]

        def on_click(self):
            # type: () -> None
            if "onClick" in self.internal_click_overrides:
                self.internal_click_overrides["onClick"][0](*self.internal_click_overrides["onClick"][1])
            if self.event_bindings["onClick"]:
                if self.event_data["onClick"]:
                    self.event_bindings["onClick"](*self.event_data["onClick"])
                else:
                    self.event_bindings["onClick"]()

        def on_long_click(self):
            # type: () -> None
            if "onLongClick" in self.internal_click_overrides:
                self.internal_click_overrides["onLongClick"][0](*self.internal_click_overrides["onLongClick"][1])
            if self.event_bindings["onLongClick"]:
                if self.event_data["onLongClick"]:
                    self.event_bindings["onLongClick"](*self.event_data["onLongClick"])
                else:
                    self.event_bindings["onLongClick"]()

        def on_intermediate_update(self):
            # type: () -> None
            if "onIntermediateUpdate" in self.internal_click_overrides:
                self.internal_click_overrides["onIntermediateUpdate"][0](
                    *self.internal_click_overrides["onIntermediateUpdate"][1])
            if self.event_bindings["onIntermediateUpdate"]:
                if self.event_data["onIntermediateUpdate"]:
                    self.event_bindings["onIntermediateUpdate"](*self.event_data["onIntermediateUpdate"])
                else:
                    self.event_bindings["onIntermediateUpdate"]()

        def set_on_click(self, mtd, data=()):
            # type: (Callable[], Optional[Tuple]) -> None
            self.event_bindings["onClick"] = mtd
            self.event_data["onClick"] = data

        def set_on_long_click(self, mtd, data=()):
            # type: (Callable[], Optional[Tuple]) -> None
            self.event_bindings["onLongClick"] = mtd
            self.event_data["onLong"] = data

        def set_on_intermediate_update(self, mtd, data=()):
            # type: (Callable[], Optional[Tuple]) -> None
            self.event_bindings["onIntermediateUpdate"] = mtd
            self.event_data["onIntermediateUpdate"] = data

        def render(self, larger_surface):
            # type: (pygame.Surface) -> None
            if self.border > 0:
                pygame.draw.rect(self.surface, self.border_color, [0, 0, self.width, self.height], self.border)
            larger_surface.blit(self.surface, self.position)

        def refresh(self):
            # type: () -> None
            self.surface = pygame.Surface((self.width, self.height), pygame.SRCALPHA)

        def get_inner_click_coordinates(self):
            # type: () -> Tuple[int, int]
            return self.inner_click_coordinates

        def check_click(self, mouse_event, offset_x=0, offset_y=0):
            self.inner_offset = [offset_x, offset_y]
            adjusted = [mouse_event.pos[0] - offset_x, mouse_event.pos[1] - offset_y]
            if adjusted[0] < 0 or adjusted[1] < 0:
                return False
            if adjusted[0] >= self.position[0] and adjusted[0] <= self.position[0] + self.width:
                if adjusted[1] >= self.position[1] and adjusted[1] <= self.position[1] + self.height:
                    self.inner_click_coordinates = tuple(adjusted)
                    if not isinstance(mouse_event, GUI.IntermediateUpdateEvent):
                        self.data["lastEvent"] = mouse_event
                    return True
            return False

        def set_position(self, pos):
            # type: (Sequence[int, int]) -> None
            self.position = list(pos)[:]

        @staticmethod
        def default(*items):
            # type: (Optional[Any, ...]) -> Tuple[Any, ...]
            if len(items) % 2 != 0:
                return items
            values = []
            p = 0
            while p < len(items):
                values.append(items[p + 1] if items[p] == DEFAULT else items[p])
                p += 2
            return tuple(values)

    class Container(Component):
        def __init__(self, position, **data):
            # type: (Tuple[int, int], Optional[Any, ...]) -> None
            super(GUI.Container, self).__init__(position, **data)
            self.transparent = False                            # type: bool
            self.background_color = (0, 0, 0)                   # type: Tuple[int, int, int]
            self.child_components = []                          # type: List[GUI.Component, ...]
            self.skip_child_check = False                       # type: bool
            self.transparent = data.get("transparent", False)
            self.background_color = data.get("color", state.get_color_palette().get_color("background"))
            if "children" in data:
                self.child_components = data["children"]

        def add_child(self, component):
            # type: (GUI.Component) -> None
            self.child_components.append(component)

        def add_children(self, *children):
            # type: (Tuple[GUI.Component, ...]) -> None
            for child in children:
                self.add_child(child)

        def remove_child(self, component):
            # type: (GUI.Component) -> None
            self.child_components.remove(component)

        def clear_children(self):
            for component in self.child_components:
                self.remove_child(component)
            del self.child_components[:]

        def get_clicked_child(self, mouse_event, offset_x=0, offset_y=0):
            curr_child = len(self.child_components)
            while curr_child > 0:
                curr_child -= 1
                child = self.child_components[curr_child]
                if "skip_child_check" in child.__dict__:
                    if child.skip_child_check:
                        if child.check_click(mouse_event, offset_x + self.position[0], offset_y + self.position[1]):
                            return child
                        else:
                            continue
                    else:
                        sub_check = child.get_clicked_child(mouse_event, offset_x + self.position[0],
                                                            offset_y + self.position[1])
                        if sub_check is None:
                            continue
                        return sub_check
                else:
                    if child.check_click(mouse_event, offset_x + self.position[0], offset_y + self.position[1]):
                        return child
            if self.check_click(mouse_event, offset_x, offset_y):
                return self
            return None

        def get_child_at(self, position):
            # type: (Tuple[int, int]) -> GUI.Component
            for child in self.child_components:
                if child.position == list(position):
                    return child
            return None

        def render(self, larger_surface):
            # type: (pygame.Surface) -> None
            if not self.transparent:
                self.surface.fill(self.background_color)
            else:
                self.surface.fill((0, 0, 0, 0))
            for child in self.child_components:
                child.render(self.surface)
            super(GUI.Container, self).render(larger_surface)

        def refresh(self, children=True):
            # type: (Optional[bool]) -> None
            super(GUI.Container, self).refresh()
            if children:
                for child in self.child_components:
                    child.refresh()

    class AppContainer(Container):
        def __init__(self, application):
            # type: (GUI.Application) -> None
            super(GUI.AppContainer, self).__init__((0, 0), width=screen.get_width(), height=screen.get_height() - 40)
            self.application = application                  # type: GUI.Application
            self.dialogs = []                               # type: List[GUI.Dialog, ...]
            self.dialog_screen_freezes = []                   # type: List[pygame.Surface, ...]
            self.dialog_components_freezes = []               # type: List[GUI.Component, ...]

        def set_dialog(self, dialog):
            # type: (GUI.Dialog) -> None
            self.dialogs.insert(0, dialog)
            self.dialog_components_freezes.insert(0, self.child_components[:])
            self.dialog_screen_freezes.insert(0, self.surface.copy())
            self.child_components = [dialog.base_container]          # type: GUI.Component

        def clear_dialog(self):
            # type: () -> None
            self.dialogs.pop(0)
            self.child_components = self.dialog_components_freezes[0]
            self.dialog_components_freezes.pop(0)
            self.dialog_screen_freezes.pop(0)

        def render(self, large_surface=None):
            # type: (Optional[pygame.Surface]) -> None
            if len(self.dialogs) == 0:
                super(GUI.AppContainer, self).render(self.surface)
            else:
                self.surface.blit(self.dialog_screen_freezes[0], (0, 0))
                self.dialogs[0].base_container.render(self.surface)
            screen.blit(self.surface, self.position)

    class Text(Component):
        def __init__(self, position, text, color=DEFAULT, size=DEFAULT, **data):
            # type: (Tuple[int, int], str, Optional[int], Optional[int], ...) -> None
            # Defaults are "item" and 14.
            color, size = GUI.Component.default(color, state.get_color_palette().get_color("item"), size, 14)
            self.text = text                                # type: str
            self.size = size                                # type: int
            self.color = color                              # type: Union[Tuple[int, int, int], int, str]
            self.font = data.get("font", state.get_font())   # type: pygame.font.Font
            self.refresh()
            data["surface"] = self.get_rendered_text()
            super(GUI.Text, self).__init__(position, **data)

        def get_rendered_text(self):
            # type: () -> pygame.Surface
            return self.font.get(self.size).render(str(self.text), 1, self.color)

        def refresh(self):
            # type: () -> None
            self.surface = self.get_rendered_text()
            self.width = self.surface.get_width()
            self.height = self.surface.get_height()

        def set_text(self, text):
            # type: (str) -> None
            self.text = str(text)
            self.refresh()

        def get_scaled_size(self, new_dimensions):
            # type: (tuple) -> int
            return new_dimensions[1] * (self.size / self.height)

    class MultiLineText(Text):
        @staticmethod
        def render_textrect(string, font, rect, text_color, background_color, justification):
            # type: (str, pygame.font.Font, pygame.Rect, Tuple[int, int, int], Tuple[int, int, int], int) -> None
            final_lines = []
            requested_lines = string.splitlines()
            err = None
            for requested_line in requested_lines:
                if font.size(requested_line)[0] > rect.width:
                    words = requested_line.split(' ')
                    for word in words:
                        if font.size(word)[0] >= rect.width:
                            print
                            "The word '" + word + "' is too long to fit in the rect passed."
                            err = 0
                    accumulated_line = ""
                    for word in words:
                        test_line = accumulated_line + word + " "
                        if font.size(test_line)[0] < rect.width:
                            accumulated_line = test_line
                        else:
                            final_lines.append(accumulated_line)
                            accumulated_line = word + " "
                    final_lines.append(accumulated_line)
                else:
                    final_lines.append(requested_line)
            surface = pygame.Surface(rect.size, pygame.SRCALPHA)
            surface.fill(background_color)
            accumulated_height = 0
            for line in final_lines:
                if accumulated_height + font.size(line)[1] >= rect.height:
                    err = 1
                if line != "":
                    tempsurface = font.render(line, 1, text_color)
                    if justification == 0:
                        surface.blit(tempsurface, (0, accumulated_height))
                    elif justification == 1:
                        surface.blit(tempsurface, ((rect.width - tempsurface.get_width()) / 2, accumulated_height))
                    elif justification == 2:
                        surface.blit(tempsurface, (rect.width - tempsurface.get_width(), accumulated_height))
                    else:
                        print
                        "Invalid justification argument: " + str(justification)
                        err = 2
                accumulated_height += font.size(line)[1]
            return (surface, err, final_lines)

        def __init__(self, position, text, color=DEFAULT, size=DEFAULT, justification=DEFAULT, **data):
            # type: (Tuple[int, int], str, Optional[int], Optiona[int], Optional[int], ...) -> None
            # Defaults are "item", and 0 (left).
            color, justification = GUI.Component.default(color, state.get_color_palette().get_color("item"),
                                                         justification, 0)
            self.justification = justification              # type: int
            self.color = color                              # type: Tuple[int, int, int]
            self.size = size                                # type: int
            # super(GUI.Text, self).__init__(position, **data)
            super(GUI.MultiLineText, self).__init__(position, text, color, size, **data)
            if self.width > state.get_gui().width:
                self.width = state.get_gui().width

        def get_rendered_text(self):
            # type: () -> pygame.Surface
            return GUI.MultiLineText.render_textrect(self.text, self.font.get(self.size),
                                                     pygame.Rect(self.position[0], self.position[1], self.width,
                                                                 self.height),
                                                     self.color, (0, 0, 0, 0), self.justification)[0]

        def refresh(self):
            self.surface = self.get_rendered_text()

    class ExpandingMultiLineText(MultiLineText):
        def __init__(self, position, text, color=DEFAULT, size=DEFAULT, justification=DEFAULT, line_height=DEFAULT,
                     **data):
            # type: (tuple, str, tuple, int, int, int) -> None
            # Defaults are "item", 14, 0, and 16.
            color, size, justification, line_height = GUI.Component.default(color,
                                                                            state.get_color_palette().get_color("item"),
                                                                            size, 14,
                                                                            justification, 0,
                                                                            line_height, 16)
            self.line_height = line_height                          # type: int
            self.linked_scroller = data.get("scroller", None)       # type: GUI.Component
            self.text_lines = []                                    # type: List[str, ...]
            super(GUI.ExpandingMultiLineText, self).__init__(position, text, color, size, justification, **data)
            self.refresh()

        def get_rendered_rext(self):
            # type: () -> pygame.Surface
            fits = False
            surf = None
            while not fits:
                d = GUI.MultiLineText.render_textrect(self.text, self.font.get(self.size),
                                                      pygame.Rect(self.position[0], self.position[1], self.width,
                                                                  self.height),
                                                      self.color, (0, 0, 0, 0), self.justification)
                surf = d[0]
                fits = d[1] != 1
                self.text_lines = d[2]
                if not fits:
                    self.height += self.line_height
            if self.linked_scroller is not None:
                self.linked_scroller.refresh(False)
            return surf

    class Image(Component):
        def __init__(self, position, **data):
            # type: (Tuple[int, int], Optional[Dict[str, Any], ...]) -> None
            self.path = ""                      # type: str
            self.originalSurface = None         # type: pygame.Surface
            self.transparent = True             # type: bool
            if "path" in data:
                self.path = data["path"]
            else:
                self.path = "surface"
            if "surface" not in data:
                data["surface"] = pygame.image.load(data["path"])
            self.originalSurface = data["surface"]
            super(GUI.Image, self).__init__(position, **data)

        def set_image(self, **data):
            # type: (...) -> None
            if "path" in data:
                self.path = data["path"]
            else:
                self.path = "surface"
            if "surface" not in data:
                data["surface"] = pygame.image.load(data["path"])
            self.originalSurface = data["surface"]
            if data.get("resize", False):
                self.width = self.originalSurface.get_width()
                self.height = self.originalSurface.get_height()
            self.refresh()

        def refresh(self):
            # type: () -> None
            super(GUI.Image, self).refresh()
            self.surface = pygame.transform.scale(self.originalSurface, (self.width, self.height))

        def render(self, larger_surface):
            # type: (pygame.Surface) -> None
            super(GUI.Image, self).render(larger_surface)

    class Slider(Component):
        def __init__(self, position, initial_pct=0, **data):
            # type: (Tuple[int, int], int, ...) -> None
            super(GUI.Slider, self).__init__(position, **data)
            self.percent = initial_pct                      # type: int
            self.background_color = data.get("backgroundColor", state.get_color_palette().get_color("background"))
            self.color = data.get("color", state.get_color_palette().get_color("item"))
            self.slider_color = data.get("sliderColor", state.get_color_palette().get_color("accent"))
            self.on_change_method = data.get("onChange", Application.dummy)
            self.refresh()

        def on_change(self):
            # type: () -> None
            self.on_change_method(self.percent)

        def set_percent(self, percent):
            # type: (int) -> None
            self.percent = percent

        def refresh(self):
            # type: () -> None
            self.percentPixels = self.width / 100.0
            super(GUI.Slider, self).refresh()

        def render(self, larger_surface):
            # type: (pygame.Surface) -> None
            self.surface.fill(self.background_color)
            pygame.draw.rect(self.surface, self.color, [0, self.height / 4, self.width, self.height / 2])
            pygame.draw.rect(self.surface, self.slider_color,
                             [(self.percent * self.percentPixels) - 15, 0, 30, self.height])
            super(GUI.Slider, self).render(larger_surface)

        def check_click(self, mouse_event, offset_x=0, offset_y=0):
            is_clicked = super(GUI.Slider, self).check_click(mouse_event, offset_x, offset_y)
            if is_clicked:
                self.percent = ((mouse_event.pos[0] - offset_x - self.position[0])) / self.percentPixels
                if self.percent > 100.0:
                    self.percent = 100.0
                self.on_change()
            return is_clicked

        def get_percent(self):
            return self.percent

    class Button(Container):
        def __init__(self, position, text, bg_color=DEFAULT, text_color=DEFAULT, text_size=DEFAULT, **data):
            # type: (tuple, str, tuple, tuple, int, ...) -> None
            # Defaults are "darker:background", "item", and 14.
            bg_color, text_color, text_size = GUI.Component.default(
                bg_color,
                state.get_color_palette().get_color("darker:background"),
                text_color, state.get_color_palette().get_color("item"),
                text_size, 14)
            self.text_component = GUI.Text((0, 0), text, text_color, text_size, font=data.get("font", state.get_font()))
            self.padding_amount = data.get("padding", 5)
            if "width" not in data:
                data["width"] = self.text_component.width + (2 * self.padding_amount)
            if "height" not in data:
                data["height"] = self.text_component.height + (2 * self.padding_amount)
            super(GUI.Button, self).__init__(position, **data)
            self.skip_child_check = True
            self.text_component.set_position(GUI.get_centered_coordinates(self.text_component, self))
            self.background_color = bg_color
            self.add_child(self.text_component)

        def set_text(self, text):
            # type: (str) -> None
            self.text_component.text = str(text)
            self.text_component.refresh()
            self.text_component.set_position(GUI.get_centered_coordinates(self.text_component, self))

        def render(self, larger_surface):
            # type: (pygame.Surface) -> None
            super(GUI.Button, self).render(larger_surface)

        def get_clicked_child(self, mouse_event, offset_x=0, offset_y=0):
            # type: (pygame.event.Event, int, int) -> GUI.Button
            if self.check_click(mouse_event, offset_x, offset_y):
                return self
            return None

    class Checkbox(Component):
        def __init__(self, position, checked=False, **data):
            # type: (Tuple[int, int], Optional[bool], ...) -> None
            if "border" not in data:
                data["border"] = 2
                data["border_color"] = state.get_color_palette().get_color("item")
            super(GUI.Checkbox, self).__init__(position, **data)
            self.background_color = data.get("background_color", state.get_color_palette().get_color("background"))
            self.check_color = data.get("checkColor", state.get_color_palette().get_color("accent"))
            self.check_width = data.get("checkWidth", self.height / 4)
            self.checked = checked
            self.internal_click_overrides["onClick"] = [self.check, ()]

        def get_checked(self):
            # type: () -> bool
            return self.checked

        def check(self, state="toggle"):
            # type: (Optional[Union[str, bool]]) -> None
            if state == "toggle":
                self.checked = not self.checked
            else:
                self.checked = bool(state)

        def render(self, larger_surface):
            # type: (pygame.Surface) -> None
            self.surface.fill(self.background_color)
            if self.checked:
                pygame.draw.lines(self.surface, self.check_color, False, [(0, self.height / 2),
                                                                          (self.width / 2,
                                                                           self.height - self.check_width / 2),
                                                                          (self.width, 0)], self.check_width)
            super(GUI.Checkbox, self).render(larger_surface)

    class Switch(Component):
        def __init__(self, position, on=False, **data):
            # type: (Tuple[int, int], bool, ...) -> None
            if "border" not in data:
                data["border"] = 2
                data["border_color"] = state.get_color_palette().get_color("item")
            super(GUI.Switch, self).__init__(position, **data)
            self.background_color = data.get("backgroundColor", state.get_color_palette().get_color("background"))
            self.on_color = data.get("onColor", state.get_color_palette().get_color("accent"))
            self.off_color = data.get("offColor", state.get_color_palette().get_color("dark:background"))
            self.on = on
            self.internal_click_overrides["onClick"] = [self.switch, ()]

        def get_checked(self):
            # type: () -> bool
            return self.checked

        def switch(self, state="toggle"):
            # type: (Optional[Union[str, bool]]) -> None
            if state == "toggle":
                self.on = not self.on
            else:
                self.on = bool(state)

        def render(self, larger_surface):
            # type: (pygame.Surface) -> None
            self.surface.fill(self.background_color)
            if self.on:
                pygame.draw.rect(self.surface, self.on_color, [self.width / 2, 0, self.width / 2, self.height])
            else:
                pygame.draw.rect(self.surface, self.off_color, [0, 0, self.width / 2, self.height])
            pygame.draw.circle(self.surface, state.get_color_palette().get_color("item"),
                               (self.width / 4, self.height / 2), self.height / 4, 2)
            pygame.draw.line(self.surface, state.get_color_palette().get_color("item"),
                             (3 * (self.width / 4), self.height / 4),
                             (3 * (self.width / 4), 3 * (self.height / 4)), 2)
            super(GUI.Switch, self).render(larger_surface)

    class Canvas(Component):
        def __init__(self, position, **data):
            # type: (Tuple[int, int], ...) -> None
            super(GUI.Canvas, self).__init__(position, **data)

    class KeyboardButton(Container):
        def __init__(self, position, symbol, alt_symbol, **data):
            # type: (Tuple[int, int], str, str, ...) -> None
            if "border" not in data:
                data["border"] = 1
                data["border_color"] = state.get_color_palette().get_color("item")
            super(GUI.KeyboardButton, self).__init__(position, **data)
            self.skip_child_check = True
            self.primary_text_component = GUI.Text((1, 0), symbol, state.get_color_palette().get_color("item"), 20,
                                                   font=state.get_typing_font())
            self.secondary_text_component = GUI.Text((self.width - 8, 0), alt_symbol,
                                                     state.get_color_palette().get_color("item"), 10,
                                                     font=state.get_typing_font())
            self.primary_text_component.set_position(
                [GUI.get_centered_coordinates(self.primary_text_component, self)[0] - 6,
                 self.height - self.primary_text_component.height - 1])
            self.add_child(self.primary_text_component)
            self.add_child(self.secondary_text_component)
            self.blink_time = 0
            self.internal_click_overrides["onClick"] = (self.register_blink, ())
            self.internal_click_overrides["onLongClick"] = (self.register_blink, (True,))

        def register_blink(self, lp=False):
            # type: (bool) -> None
            self.blink_time = state.get_gui().update_interval / 4
            self.primary_text_component.color = state.get_color_palette().get_color("background")
            self.secondary_text_component.color = state.get_color_palette().get_color("background")
            self.background_color = state.get_color_palette().get_color("accent" if lp else "item")
            self.refresh()

        def get_clicked_child(self, mouse_event, offset_x=0, offset_y=0):
            # type: (pygame.event.Event, Optional[int], Optional[int]) -> GUI.KeyboardButton
            if self.check_click(mouse_event, offset_x, offset_y):
                return self
            return None

        def render(self, larger_surface):
            # type: (pygame.Surface) -> None
            if self.blink_time >= 0:
                self.blink_time -= 1
                if self.blink_time < 0:
                    self.primary_text_component.color = state.get_color_palette().get_color("item")
                    self.secondary_text_component.color = state.get_color_palette().get_color("item")
                    self.background_color = state.get_color_palette().get_color("background")
                    self.refresh()
            super(GUI.KeyboardButton, self).render(larger_surface)

    class TextEntryField(Container):
        def __init__(self, position, initial_text="", **data):
            if "border" not in data:
                data["border"] = 1
                data["border_color"] = state.get_color_palette().get_color("accent")
            if "textColor" not in data:
                data["textColor"] = state.get_color_palette().get_color("item")
            if "blink" in data:
                self.blinkInterval = data["blink"]
            else:
                self.blinkInterval = 500
            self.do_blink = True
            self.blinkOn = False
            self.lastBlink = datetime.now()
            self.indicator_position = len(initial_text)
            self.indicator_px_position = 0
            super(GUI.TextEntryField, self).__init__(position, **data)
            self.skip_child_check = True
            self.text_component = GUI.Text((2, 0), initial_text, data["textColor"], 16, font=state.get_typing_font())
            self.update_overflow()
            self.last_click_coord = None
            self.text_component.position[1] = GUI.get_centered_coordinates(self.text_component, self)[1]
            self.add_child(self.text_component)
            self.multiline = None
            self.internal_click_overrides["onClick"] = (self.activate, ())
            self.internal_click_overrides["onIntermediateUpdate"] = (self.drag_scroll, ())

        def clear_scroll_params(self):
            # type: () -> None
            self.last_click_coord = None

        def drag_scroll(self):
            # type: () -> None
            if self.last_click_coord is not None and self.overflow > 0:
                ydist = self.inner_click_coordinates[1] - self.last_click_coord[1]
                self.overflow -= ydist
                if self.overflow > 0 and self.overflow + self.width < self.text_component.width:
                    self.text_component.position[0] = 2 - self.overflow
                else:
                    self.text_component.position[0] = 2
            self.last_click_coord = self.inner_click_coordinates

        def get_px_position(self, from_pos=DEFAULT):
            # type: (int) -> int
            return state.get_typing_font().get(16).render(
                self.text_component.text[:(self.indicator_position if from_pos == DEFAULT else from_pos)], 1,
                self.text_component.color).get_width()

        def activate(self):
            # type: () -> GUI.TextEntryField
            self.clear_scroll_params()
            self.update_overflow()
            state.set_keyboard(GUI.Keyboard(self))
            if self.multiline is not None:
                for f in self.multiline.textFields:
                    f.do_blink = False
            self.do_blink = True
            mouse_pos = self.inner_click_coordinates[0] - self.inner_offset[0]
            if mouse_pos > self.text_component.width:
                self.indicator_position = len(self.text_component.text)
            else:
                prev_width = 0
                for self.indicator_position in range(len(self.text_component.text)):
                    curr_width = self.get_px_position(self.indicator_position)
                    if mouse_pos >= prev_width and mouse_pos <= curr_width:
                        self.indicator_position -= 1
                        break
                    prev_width = curr_width
            state.get_keyboard().active = True
            self.indicator_px_position = self.get_px_position()
            if self.multiline:
                self.multiline.set_current(self)
            return self

        def update_overflow(self):
            # type: () -> None
            self.overflow = max(self.text_component.width - (self.width - 4), 0)
            if self.overflow > 0:
                self.text_component.position[0] = 2 - self.overflow
            else:
                self.text_component.position[0] = 2

        def append_char(self, char):
            # type: (str) -> None
            if self.indicator_position == len(self.text_component.text) - 1:
                self.text_component.text += char
            else:
                self.text_component.text = self.text_component.text[
                                           :self.indicator_position] + char + self.text_component.text[
                                                                             self.indicator_position:]
            self.text_component.refresh()
            self.indicator_position += len(char)
            self.update_overflow()
            if self.multiline is not None:
                if self.overflow > 0:
                    newt = self.text_component.text[max(self.text_component.text.rfind(" "),
                                                        self.text_component.text.rfind("-")):]
                    self.text_component.text = self.text_component.text.rstrip(newt)
                    self.multiline.add_field(newt)
                    self.multiline.wrappedLines.append(self.multiline.currentField)
                    # if self.multiline.currentField == len(self.multiline.textFields)-1:
                    #    self.multiline.addField(newt)
                    # else:
                    #    self.multiline.prependToNextField(newt)
                    self.text_component.refresh()
                    self.update_overflow()
            self.indicator_px_position = self.get_px_position()

        def backspace(self):
            # type: () -> None
            if self.indicator_position >= 1:
                self.indicator_position -= 1
                self.indicator_px_position = self.get_px_position()
                self.text_component.text = (self.text_component.text[:self.indicator_position] +
                                            self.text_component.text[self.indicator_position + 1:])
                self.text_component.refresh()
            else:
                if self.multiline is not None and self.multiline.currentField > 0:
                    self.multiline.remove_field(self)
                    self.multiline.textFields[self.multiline.currentField - 1].append_char(
                        self.text_component.text.strip(" "))
                    self.multiline.textFields[self.multiline.currentField - 1].activate()
            self.update_overflow()

        def delete(self):
            # type: () -> None
            if self.indicator_position < len(self.text_component.text):
                self.text_component.text = (self.text_component.text[:self.indicator_position] +
                                            self.text_component.text[self.indicator_position + 1:])
                self.text_component.refresh()
            self.update_overflow()
            if self.multiline is not None:
                self.append_char(self.multiline.get_delete_char())

        def get_text(self):
            # type: () -> str
            return self.text_component.text

        def refresh(self, children=False):
            # type: (bool) -> None
            self.update_overflow()
            super(GUI.TextEntryField, self).refresh()

        def render(self, larger_surface):
            # type: (pygame.Surface) -> None
            if not self.transparent:
                self.surface.fill(self.background_color)
            else:
                self.surface.fill((0, 0, 0, 0))
            for child in self.child_components:
                child.render(self.surface)
            if self.do_blink:
                if ((datetime.now() - self.lastBlink).microseconds / 1000) >= self.blinkInterval:
                    self.lastBlink = datetime.now()
                    self.blinkOn = not self.blinkOn
                if self.blinkOn:
                    pygame.draw.rect(self.surface, self.text_component.color,
                                     [self.indicator_px_position, 2, 2, self.height - 4])
            super(GUI.Container, self).render(larger_surface)

        def get_clicked_child(self, mouse_event, offset_x=0, offset_y=0):
            # type: (pygame.event.Event, int, int) -> GUI.TextEntryField
            if self.check_click(mouse_event, offset_x, offset_y):
                return self
            return None

    class PagedContainer(Container):
        def __init__(self, position, **data):
            super(GUI.PagedContainer, self).__init__(position, **data)
            self.pages = data.get("pages", [])                                      # type: List[GUI.Container,...]
            self.current_page = 0                                                   # type: int
            self.hide_controls = data.get("hideControls", False)                    # type: bool
            self.page_controls = GUI.Container((0, self.height - 20),
                                               color=state.get_color_palette().get_color("background"),
                                               width=self.width,
                                               height=20)                           # type: GUI.Container
            self.page_left_button = GUI.Button((0, 0), " < ", state.get_color_palette().get_color("item"),
                                               state.get_color_palette().get_color("accent"),
                                               16, width=40, height=20, onClick=self.page_left,
                                               onLongClick=self.goto_page)           # type: GUI.Button
            self.page_right_button = GUI.Button((self.width - 40, 0), " > ",
                                                state.get_color_palette().get_color("item"),
                                                state.get_color_palette().get_color("accent"),
                                                16, width=40, height=20, onClick=self.page_right,
                                                onLongClick=self.goto_last_page)      # type: GUI.Button
            self.page_indicator_text = GUI.Text((0, 0), str(self.current_page + 1) + " of " + str(len(self.pages)),
                                                state.get_color_palette().get_color("item"),
                                                16)                                 # type: GUI.Text
            self.page_holder = GUI.Container((0, 0), color=state.get_color_palette().get_color("background"),
                                             width=self.width,
                                             height=(self.height - 20 if not self.hide_controls else self.height)
                                             )                                      # type: GUI.Container
            self.page_indicator_text.position[0] = GUI.get_centered_coordinates(
                self.page_indicator_text, self.page_controls)[0]
            super(GUI.PagedContainer, self).add_child(self.page_holder)
            self.page_controls.add_child(self.page_left_button)
            self.page_controls.add_child(self.page_indicator_text)
            self.page_controls.add_child(self.page_right_button)
            if not self.hide_controls:
                super(GUI.PagedContainer, self).add_child(self.page_controls)

        def add_page(self, page):
            # type: (GUI.Container) -> None
            self.pages.append(page)
            self.page_indicator_text.text = str(self.current_page + 1) + " of " + str(len(self.pages))
            self.page_indicator_text.refresh()

        def get_page(self, number):
            # type: (int) -> GUI.Container
            return self.pages[number]

        def page_left(self):
            # type: () -> None
            if self.current_page >= 1:
                self.goto_page(self.current_page - 1)

        def page_right(self):
            # type: () -> None
            if self.current_page < len(self.pages) - 1:
                self.goto_page(self.current_page + 1)

        def goto_page(self, number=0):
            # type: (int) -> None
            self.current_page = number
            self.page_holder.clear_children()
            self.page_holder.add_child(self.get_page(self.current_page))
            self.page_indicator_text.set_text(str(self.current_page + 1) + " of " + str(len(self.pages)))
            self.page_indicator_text.refresh()

        def goto_last_page(self):
            # type: () -> None
            self.goto_page(len(self.pages) - 1)

        def get_last_page(self):
            # type: () -> GUI.Container
            return self.pages[-1]

        def generate_page(self, **data):
            # type: (...) -> GUI.Container
            if "width" not in data:
                data["width"] = self.page_holder.width
            if "height" not in data:
                data["height"] = self.page_holder.height
            data["isPage"] = True
            return GUI.Container((0, 0), **data)

        def add_child(self, component):
            # type: (GUI.Component) -> None
            if isinstance(self.pages, list):
                self.add_page(self.generate_page(color=self.background_color, width=self.page_holder.width,
                                                 height=self.page_holder.height))
            self.get_last_page().add_child(component)

        def remove_child(self, component):
            # type: (GUI.Component) -> None
            self.pages[self.current_page].remove_child(component)
            children_copy = self.pages[self.current_page].child_components[:]
            for page in self.pages:
                for child in page.child_components:
                    page.remove_child(child)
            for child in children_copy:
                self.add_child(child)

        def remove_page(self, page):
            # type: (Union[int, GUI.Container]) -> None
            if isinstance(page, int):
                self.pages.pop(page)
            else:
                self.pages.remove(page)
            if self.current_page >= len(self.pages):
                self.goto_page(self.current_page - 1)

        def clear_children(self):
            # type: () -> None
            self.pages = []
            self.add_page(self.generate_page(color=self.background_color))
            self.goto_page()

    class GriddedPagedContainer(PagedContainer):
        def __init__(self, position, rows=5, columns=4, **data):
            # type: () -> None
            self.padding = 5
            if "padding" in data:
                self.padding = data["padding"]
            self.rows = rows
            self.columns = columns
            super(GUI.PagedContainer, self).__init__(position, **data)
            self.perRow = ((self.height - 20) - (2 * self.padding)) / rows
            self.perColumn = (self.width - (2 * self.padding)) / columns
            super(GUI.GriddedPagedContainer, self).__init__(position, **data)

        def is_page_filled(self, number):
            # type: (int) -> bool
            if isinstance(number, int):
                return len(self.pages[number].child_components) == (self.rows * self.columns)
            else:
                return len(number.child_components) == (self.rows * self.columns)

        def add_child(self, component):
            # type: (GUI.Component) -> None
            if len(self.pages) == 0 or self.is_page_filled(self.get_last_page()):
                self.add_page(self.generate_page(color=self.background_color))
            new_child_position = [self.padding, self.padding]
            if self.get_last_page().child_components == []:
                component.set_position(new_child_position)
                self.get_last_page().add_child(component)
                return
            last_child_position = self.get_last_page().child_components[
                                    len(self.get_last_page().child_components) - 1].position[:]
            if last_child_position[0] < self.padding + (self.perColumn * (self.columns - 1)):
                new_child_position = [last_child_position[0] + self.perColumn, last_child_position[1]]
            else:
                new_child_position = [self.padding, last_child_position[1] + self.perRow]
            component.set_position(new_child_position)
            self.get_last_page().add_child(component)

    class ListPagedContainer(PagedContainer):
        def __init__(self, position, **data):
            # type: (Tuple[int, int], ...) -> None
            self.padding = data.get("padding", 0)
            self.margin = data.get("margin", 0)
            super(GUI.ListPagedContainer, self).__init__(position, **data)

        def get_height_of_components(self):
            height = self.padding
            if self.pages == []:
                return self.padding
            for component in self.get_last_page().child_components:
                height += component.height + (2 * self.margin)
            return height

        def add_child(self, component):
            # type: (GUI.Component) -> None
            component_height = self.get_height_of_components()
            if self.pages == [] or component_height + (component.height + 2 * self.margin) + (
                    2 * self.padding) >= self.page_holder.height:
                self.add_page(self.generate_page(color=self.background_color))
                component_height = self.get_height_of_components()
            component.set_position([self.padding, component_height])
            self.get_last_page().add_child(component)
            component.refresh()

        def remove_child(self, component):
            # type: (GUI.Component) -> None
            super(GUI.ListPagedContainer, self).remove_child(component)
            if self.pages[0].child_components == []:
                self.remove_page(0)
                self.goto_page()

    class ButtonRow(Container):
        def __init__(self, position, **data):
            # type: (Tuple[int, int], ...) -> None
            self.padding = data.get("padding", 0)
            self.margin = data.get("margin", 0)
            super(GUI.ButtonRow, self).__init__(position, **data)

        def get_last_component(self):
            # type: () -> GUI.Component
            if len(self.child_components) > 0:
                return self.child_components[len(self.child_components) - 1]
            return None

        def add_child(self, component):
            # type: (GUI.Component) -> None
            component.height = self.height - (2 * self.padding)
            last = self.get_last_component()
            if last is not None:
                component.set_position([last.position[0] + last.width + self.margin, self.padding])
            else:
                component.set_position([self.padding, self.padding])
            super(GUI.ButtonRow, self).add_child(component)

        def remove_child(self, component):
            super(GUI.ButtonRow, self).remove_child(component)
            children_copy = self.child_components[:]
            self.clear_children()
            for child in children_copy:
                self.add_child(child)

    class ScrollIndicator(Component):
        def __init__(self, scroll_cont, position, color, **data):
            # type: (GUI.Container, Tuple[int, int], Tuple[int, int, int], ...) -> None
            super(GUI.ScrollIndicator, self).__init__(position, **data)
            self.internal_click_overrides["onIntermediateUpdate"] = (self.drag_scroll, ())
            self.internal_click_overrides["onClick"] = (self.clear_scroll_params, ())
            self.internal_click_overrides["onLongClick"] = (self.clear_scroll_params, ())
            self.scroll_container = scroll_cont
            self.color = color
            self.last_click_coord = None

        def update(self):
            # type: () -> None
            self.pct = 1.0 * self.scroll_container.height / self.scroll_container.maxOffset
            self.slide = -self.scroll_container.offset * self.pct
            self.sih = self.pct * self.height

        def render(self, larger_surface):
            # type: (pygame.Surface) -> None
            self.surface.fill(self.color)
            pygame.draw.rect(self.surface, state.get_color_palette().get_color("accent"),
                             [0, int(self.slide * (1.0 * self.height / self.scroll_container.height)), self.width,
                              int(self.sih)])
            super(GUI.ScrollIndicator, self).render(larger_surface)

        def clear_scroll_params(self):
            # type: () -> None
            self.last_click_coord = None

        def drag_scroll(self):
            # type: () -> None
            if self.last_click_coord is not None:
                ydist = self.inner_click_coordinates[1] - self.last_click_coord[1]
                self.scroll_container.scroll(ydist)
            self.last_click_coord = self.inner_click_coordinates

    class ScrollableContainer(Container):
        def __init__(self, position, **data):
            self.scrollAmount = data.get("scrollAmount", 15)
            super(GUI.ScrollableContainer, self).__init__(position, **data)
            self.container = GUI.Container((0, 0), transparent=True, width=self.width - 20, height=self.height)
            self.scrollBar = GUI.Container((self.width - 20, 0), width=20, height=self.height)
            self.scrollUpBtn = GUI.Image((0, 0), path="res/scrollup.png", width=20, height=40,
                                         onClick=self.scroll, onClickData=(self.scrollAmount,))
            self.scrollDownBtn = GUI.Image((0, self.scrollBar.height - 40), path="res/scrolldown.png", width=20,
                                           height=40,
                                           onClick=self.scroll, onClickData=(-self.scrollAmount,))
            self.scrollIndicator = GUI.ScrollIndicator(self, (0, 40), self.background_color, width=20,
                                                       height=self.scrollBar.height - 80, border=1,
                                                       borderColor=state.get_color_palette().get_color("item"))
            if self.height >= 120:
                self.scrollBar.add_child(self.scrollIndicator)
            self.scrollBar.add_child(self.scrollUpBtn)
            self.scrollBar.add_child(self.scrollDownBtn)
            super(GUI.ScrollableContainer, self).add_child(self.container)
            super(GUI.ScrollableContainer, self).add_child(self.scrollBar)
            self.offset = 0
            self.minOffset = 0
            self.maxOffset = self.height
            self.scrollIndicator.update()

        def scroll(self, amount):
            # type: (int) -> None
            if amount < 0:
                if self.offset - amount - self.height <= -self.maxOffset:
                    self.scroll_to(-self.maxOffset + self.height)
                    return
            else:
                if self.offset + amount > self.minOffset:
                    self.scroll_to(self.minOffset)
                    return
            for child in self.container.child_components:
                child.position[1] = child.position[1] + amount
            self.offset += amount
            self.scrollIndicator.update()

        def scroll_to(self, amount):
            # type: (int) -> None
            self.scroll(-self.offset)
            self.scroll(amount)

        def get_visible_children(self):
            # type: () -> List[Component]
            visible = []
            for child in self.container.child_components:
                if child.position[1] + child.height >= 0 and child.position[1] - child.height <= self.height:
                    visible.append(child)
            return visible

        def get_clicked_child(self, mouse_event, offset_x=0, offset_y=0):
            if not self.check_click(mouse_event, offset_x, offset_y):
                return None
            clicked = self.scrollBar.get_clicked_child(
                mouse_event, offset_x + self.position[0], offset_y + self.position[1])
            if clicked is not None:
                return clicked
            visible = self.get_visible_children()
            curr_child = len(visible)
            while curr_child > 0:
                curr_child -= 1
                child = visible[curr_child]
                if "skip_child_check" in child.__dict__:
                    if child.skip_child_check:
                        if child.check_click(mouse_event, offset_x + self.position[0], offset_y + self.position[1]):
                            return child
                        else:
                            continue
                    else:
                        sub_check = child.get_clicked_child(
                            mouse_event, offset_x + self.position[0],
                            offset_y + self.position[1])
                        if sub_check is None:
                            continue
                        return sub_check
                else:
                    if child.check_click(mouse_event, offset_x + self.position[0], offset_y + self.position[1]):
                        return child
            if self.check_click(mouse_event, offset_x, offset_y):
                return self
            return None

        def add_child(self, component):
            # type: (GUI.Component) -> None
            if component.position[1] < self.minOffset:
                self.minOffset = component.position[1]
            if component.position[1] + component.height > self.maxOffset:
                self.maxOffset = component.position[1] + component.height
            self.container.add_child(component)
            self.scrollIndicator.update()

        def remove_child(self, component):
            # type: (GUI.Component) -> None
            self.container.remove_child(component)
            if component.position[1] == self.minOffset:
                self.minOffset = 0
                for comp in self.container.child_components:
                    if comp.position[1] < self.minOffset:
                        self.minOffset = comp.position[1]
            if component.position[1] == self.maxOffset:
                self.maxOffset = self.height
                for comp in self.container.child_components:
                    if comp.position[1] + comp.height > self.maxOffset:
                        self.maxOffset = comp.position[1] + comp.height
            self.scrollIndicator.update()

        def clear_children(self):
            # type: () -> None
            self.container.clear_children()
            self.maxOffset = self.height
            self.offset = 0
            self.scrollIndicator.update()

        def render(self, larger_surface):
            # type: (pygame.Surface) -> None
            super(GUI.ScrollableContainer, self).render(larger_surface)

        def refresh(self, children=True):
            self.minOffset = 0
            for comp in self.container.child_components:
                if comp.position[1] < self.minOffset:
                    self.minOffset = comp.position[1]
            self.maxOffset = self.height
            for comp in self.container.child_components:
                if comp.position[1] + comp.height > self.maxOffset:
                    self.maxOffset = comp.position[1] + comp.height
            self.scrollIndicator.update()
            self.container.refresh(children)

    class ListScrollableContainer(ScrollableContainer):
        def __init__(self, position, **data):
            # type: (Tuple[int, int], ...) -> None
            self.margin = data.get("margin", 0)
            super(GUI.ListScrollableContainer, self).__init__(position, **data)

        def get_cumulative_height(self):
            # type: () -> int
            height = 0
            if len(self.container.child_components) == 0:
                height = 0
            for component in self.container.child_components:
                height += component.height + self.margin
            return height

        def add_child(self, component):
            # type: (GUI.Component) -> None
            component.position[1] = self.get_cumulative_height()
            super(GUI.ListScrollableContainer, self).add_child(component)

        def remove_child(self, component):
            # type: (GUI.Component) -> None
            super(GUI.ListScrollableContainer, self).remove_child(component)
            children_copy = self.container.child_components[:]
            del self.container.child_components[:]
            for child in children_copy:
                self.add_child(child)

    class TextScrollableContainer(ScrollableContainer):
        def __init__(self, position, text_component=DEFAULT, **data):
            # type: (Tuple[int, int], GUI.Text, ...) -> None
            # Defaults to creating a text component.
            data["scrollAmount"] = data.get(
                "line_height", text_component.lineHeight if text_component != DEFAULT else 16)

            super(GUI.TextScrollableContainer, self).__init__(position, **data)
            if text_component == DEFAULT:
                self.textComponent = GUI.ExpandingMultiLineText((0, 0), "", state.get_color_palette().get_color("item"),
                                                                width=self.container.width,
                                                                height=self.container.height, scroller=self)
            else:
                self.textComponent = text_component                      # type: GUI.Text
                if self.textComponent.width == self.width:
                    self.textComponent.width = self.container.width
                    self.textComponent.refresh()
            self.add_child(self.textComponent)

        def get_text_component(self):
            # type: () -> GUI.Text
            return self.textComponent

    class MultiLineTextEntryField(ListScrollableContainer):
        def __init__(self, position, initial_text="", **data):
            # type: (Tuple[int, int], str, ...) -> None
            if "border" not in data:
                data["border"] = 1
                data["border_color"] = state.get_color_palette().get_color("accent")
            data["onClick"] = self.activate_last
            data["onClickData"] = ()
            super(GUI.MultiLineTextEntryField, self).__init__(position, **data)
            self.line_height = data.get("line_height", 20)                      # type: int
            self.max_lines = data.get("maxLines", -2)                           # type: int
            self.background_color = data.get("background_color", state.get_color_palette().get_color("background"))
            self.text_color = data.get("color", state.get_color_palette().get_color("item"))
            self.text_fields = []                                               # type: list
            self.wrapped_lines = []                                             # type: list
            self.current_field = -1                                             # type: int
            self.set_text(initial_text)

        def activate_last(self):
            # type: () -> None
            self.current_field = len(self.text_fields) - 1
            self.text_fields[self.current_field].activate()

        def refresh(self, children=True):
            # type: (Optional[bool]) -> None
            self.clear_children()
            for tf in self.text_fields:
                self.add_child(tf)

        def set_current(self, field):
            # type: (int) -> None
            self.current_field = self.text_fields.index(field)

        def add_field(self, initial_text):
            # type: (str) -> None
            if len(self.text_fields) == self.max_lines:
                return
            field = GUI.TextEntryField((0, 0), initial_text, width=self.container.width, height=self.line_height,
                                       backgroundColor=self.background_color, textColor=self.text_color)
            field.border = 0
            field.multiline = self
            self.current_field += 1
            self.text_fields.insert(self.current_field, field)
            field.activate()
            self.refresh()

        #         def prependToNextField(self, text): #HOLD FOR NEXT RELEASE
        #             print "Prep: "+text
        #             self.currentField += 1
        #             currentText = self.textFields[self.currentField].textComponent.text
        #             self.textFields[self.currentField].textComponent.text = ""
        #             self.textFields[self.currentField].indicatorPosition = 0
        #             self.textFields[self.currentField].refresh()
        #             self.textFields[self.currentField].activate()
        #             for word in (" "+text+" "+currentText).split(" "):
        #                 self.textFields[self.currentField].appendChar(word+" ")
        #             self.textFields[self.currentField].refresh()

        def remove_field(self, field):
            # type: (str) -> None
            if self.current_field > 0:
                if self.text_fields.index(field) == self.current_field:
                    self.current_field -= 1
                self.text_fields.remove(field)
            self.refresh()

        def get_delete_char(self):
            # type: () -> str
            if self.current_field < len(self.text_fields) - 1:
                c = ""
                try:
                    c = self.text_fields[self.current_field + 1].textComponent.text[0]
                    textcomp = self.text_fields[self.current_field + 1].textComponent
                    textcomp.text = self.text_fields[self.current_field + 1].textComponent.text[1:]
                    self.text_fields[self.current_field + 1].update_overflow()
                    self.text_fields[self.current_field + 1].refresh()
                except:
                    self.remove_field(self.text_fields[self.current_field + 1])
                return c
            return ""

        def get_text(self):
            # type: () -> str
            t = ""
            p = 0
            for ftext in [f.get_text() for f in self.text_fields]:
                if p in self.wrapped_lines:
                    t += ftext
                else:
                    t += ftext + "\n"
                p += 1
            t.rstrip("\n")
            return t

        def clear(self):
            # type: () -> None
            self.text_fields = []
            self.wrapped_lines = []
            self.current_field = -1
            self.refresh()

        def set_text(self, text):
            self.clear()
            if text == "":
                self.add_field("")
            else:
                for line in text.replace("\r", "").split("\n"):
                    self.add_field("")
                    line = line.rstrip()
                    words = line.split(" ")
                    old_n = self.current_field
                    for word in words:
                        self.text_fields[self.current_field].append_char(word)
                        self.text_fields[self.current_field].append_char(" ")
                    if old_n != self.current_field:
                        for n in range(old_n, self.current_field):
                            self.wrapped_lines.append(n)
                for field in self.text_fields:
                    if field.overflow > 0:
                        field.textComponent.set_text(field.textComponent.text.rstrip(" "))
                        field.update_overflow()
            self.refresh()
            state.get_keyboard().deactivate()

    class FunctionBar(object):
        def __init__(self):
            self.container = GUI.Container((0, state.get_gui().height - 40),
                                           background=state.get_color_palette().get_color("background"),
                                           width=state.get_gui().width, height=40)
            self.launcherApp = state.get_application_list().get_app("launcher")
            self.notificationMenu = GUI.NotificationMenu()
            self.recentAppSwitcher = GUI.RecentAppSwitcher()
            self.menu_button = GUI.Image((0, 0), surface=state.get_icons().get_loaded_icon("menu"),
                                         onClick=self.activate_launcher, onLongClick=Application.full_close_current)
            self.app_title_text = GUI.Text((42, 8), "Python OS 6", state.get_color_palette().get_color("item"), 20,
                                           onClick=self.toggle_recent_ap_switcher)
            self.clock_text = GUI.Text((state.get_gui().width - 45, 8), self.format_time(),
                                       state.get_color_palette().get_color("accent"), 20,
                                       onClick=self.toggle_notification_nenu,
                                       onLongClick=State.rescue)  # Add Onclick Menu
            self.container.add_child(self.menu_button)
            self.container.add_child(self.app_title_text)
            self.container.add_child(self.clock_text)

        def format_time(self):
            time = str(datetime.now())
            if time.startswith("0"):
                time = time[1:]
            return time[time.find(" ") + 1:time.find(":", time.find(":") + 1)]

        def render(self):
            if state.get_notification_queue().new:
                self.clock_text.color = (255, 59, 59)
            self.clock_text.text = self.format_time()
            self.clock_text.refresh()
            self.container.render(screen)

        def activate_launcher(self):
            if state.get_active_application() != self.launcherApp:
                self.launcherApp.activate()
            else:
                Application.full_close_current()

        def toggle_notification_nenu(self):
            if self.notificationMenu.displayed:
                self.notificationMenu.hide()
                return
            else:
                self.notificationMenu.display()

        def toggle_recent_ap_switcher(self):
            if self.recentAppSwitcher.displayed:
                self.recentAppSwitcher.hide()
                return
            else:
                self.recentAppSwitcher.display()

    class Keyboard(object):
        def __init__(self, text_entry_field=None):
            self.shift_up = False
            self.active = False
            self.text_entry_field = text_entry_field
            self.moved_ui = False
            if (self.text_entry_field.position[1] + self.text_entry_field.height > state.get_gui().height - 120 or
                    self.text_entry_field.data.get("slideUp", False)):
                state.get_active_application().ui.set_position((0, -80))
                self.moved_ui = True
            self.base_container = GUI.Container(
                (0, state.get_gui().height - 120), width=state.get_gui().width, height=120)
            self.key_width = self.base_container.width / 10
            self.key_height = self.base_container.height / 4
            # self.shift_sym = u"\u21E7" Use pygame.freetype?
            # self.enter_sym = u"\u23CE"
            # self.bkspc_sym = u"\u232B"
            # self.delet_sym = u"\u2326"
            self.shift_sym = "sh"
            self.enter_sym = "->"
            self.bkspc_sym = "<-"
            self.delet_sym = "del"
            self.keys1 = [["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"],
                          ["a", "s", "d", "f", "g", "h", "j", "k", "l", self.enter_sym],
                          [self.shift_sym, "z", "x", "c", "v", "b", "n", "m", ",", "."],
                          ["!", "?", " ", "", "", "", "", "-", "'", self.bkspc_sym]]
            self.keys2 = [["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
                          ["@", "#", "$", "%", "^", "&", "*", "(", ")", "_"],
                          ["=", "+", "\\", "/", "<", ">", "|", "[", "]", ":"],
                          [";", "{", "}", "", "", "", "", "-", "\"", self.delet_sym]]
            row = 0
            for symrow in self.keys1:
                sym = 0
                for symbol in symrow:
                    button = None
                    if symbol == "":
                        sym += 1
                        continue
                    if symbol == " ":
                        button = GUI.KeyboardButton((sym * self.key_width, row * self.key_height), "",
                                                    self.keys2[row][sym],
                                                    onClick=self.insert_char, onClickData=(self.keys1[row][sym],),
                                                    onLongClick=self.insert_char,
                                                    onLongClickData=(self.keys2[row][sym],),
                                                    width=self.key_width * 5, height=self.key_height)
                    else:
                        if (symbol == self.shift_sym or symbol == self.enter_sym or
                                symbol == self.bkspc_sym or symbol == self.delet_sym):
                            button = GUI.KeyboardButton((sym * self.key_width, row * self.key_height),
                                                        self.keys1[row][sym], self.keys2[row][sym],
                                                        onClick=self.insert_char, onClickData=(self.keys1[row][sym],),
                                                        onLongClick=self.insert_char,
                                                        onLongClickData=(self.keys2[row][sym],),
                                                        width=self.key_width, height=self.key_height, border=1,
                                                        borderColor=state.get_color_palette().get_color("accent"))
                        else:
                            button = GUI.KeyboardButton((sym * self.key_width, row * self.key_height),
                                                        self.keys1[row][sym], self.keys2[row][sym],
                                                        onClick=self.insert_char, onClickData=(self.keys1[row][sym],),
                                                        onLongClick=self.insert_char,
                                                        onLongClickData=(self.keys2[row][sym],),
                                                        width=self.key_width, height=self.key_height)
                    self.base_container.add_child(button)
                    sym += 1
                row += 1

        def deactivate(self):
            self.active = False
            if self.moved_ui:
                state.get_active_application().ui.position[1] = 0
            self.text_entry_field = None

        def set_text_entry_field(self, field):
            self.text_entry_field = field
            self.active = True
            if (self.text_entry_field.position[1] + self.text_entry_field.height > state.get_gui().height - 120 or
                    self.text_entry_field.data.get("slideUp", False)):
                state.get_active_application().ui.set_position((0, -80))
                self.moved_ui = True

        def get_entered_text(self):
            return self.text_entry_field.get_text()

        def insert_char(self, char):
            if char == self.shift_sym:
                self.shift_up = not self.shift_up
                for button in self.base_container.child_components:
                    if self.shift_up:
                        button.primaryTextComponent.text = button.primaryTextComponent.text.upper()
                    else:
                        button.primaryTextComponent.text = button.primaryTextComponent.text.lower()
                    button.primaryTextComponent.refresh()
                return
            if char == self.enter_sym:
                mult = self.text_entry_field.multiline
                self.deactivate()
                if mult is not None:
                    mult.textFields[mult.currentField].do_blink = False
                    mult.add_field("")
                return
            if char == self.bkspc_sym:
                self.text_entry_field.backspace()
                return
            if char == self.delet_sym:
                self.text_entry_field.delete()
            else:
                if self.shift_up:
                    self.text_entry_field.append_char(char.upper())
                    self.shift_up = False
                    for button in self.base_container.child_components:
                        button.primaryTextComponent.text = button.primaryTextComponent.text.lower()
                        button.primaryTextComponent.refresh()
                else:
                    self.text_entry_field.append_char(char)

        def render(self, larger_surface):
            self.base_container.render(larger_surface)

    class Overlay(object):
        def __init__(self, position, **data):
            self.position = list(position)
            self.displayed = False
            self.width = data.get("width", state.get_gui().width)
            self.height = data.get("height", state.get_gui().height - 40)
            self.color = data.get("color", state.get_color_palette().get_color("background"))
            self.base_container = GUI.Container((0, 0), width=state.get_gui().width,
                                                height=state.get_active_application().ui.height, color=(0, 0, 0, 0),
                                                onClick=self.hide)
            self.container = data.get("container", GUI.Container(self.position[:], width=self.width, height=self.height,
                                                                 color=self.color))
            self.base_container.add_child(self.container)
            self.application = state.get_active_application()

        def display(self):
            self.application = state.get_active_application()
            self.application.ui.set_dialog(self)
            self.displayed = True

        def hide(self):
            self.application.ui.clear_dialog()
            self.application.ui.refresh()
            self.displayed = False

        def add_child(self, child):
            self.container.add_child(child)

    class Dialog(Overlay):
        def __init__(self, title, text, action_buttons, on_response_recorded=None,
                     on_response_recorded_data=(), **data):
            super(GUI.Dialog, self).__init__((0, (state.get_active_application().ui.height / 2) - 65),
                                             height=data.get("height", 130),
                                             width=data.get("width", state.get_gui().width),
                                             color=data.get("color", state.get_color_palette().get_color("background")))
            self.container.border = 3
            self.container.border_color = state.get_color_palette().get_color("item")
            self.container.refresh()
            self.application = state.get_active_application()
            self.title = title
            self.text = text
            self.response = None
            self.buttonList = GUI.Dialog.get_button_list(action_buttons, self) if type(
                action_buttons[0]) == str else action_buttons
            self.text_component = GUI.MultiLineText((2, 2), self.text, state.get_color_palette().get_color("item"), 16,
                                                    width=self.container.width - 4, height=96)
            self.buttonRow = GUI.ButtonRow((0, 96), width=state.get_gui().width, height=40, color=(0, 0, 0, 0),
                                           padding=0, margin=0)
            for button in self.buttonList:
                self.buttonRow.add_child(button)
            self.add_child(self.text_component)
            self.add_child(self.buttonRow)
            self.on_response_recorded = on_response_recorded
            self.on_response_recorded_data = on_response_recorded_data

        def display(self):
            state.get_function_bar().app_title_text.set_text(self.title)
            self.application.ui.set_dialog(self)

        def hide(self):
            state.get_function_bar().app_title_text.set_text(state.get_active_application().title)
            self.application.ui.clear_dialog()
            self.application.ui.refresh()

        def record_response(self, response):
            self.response = response
            self.hide()
            if self.on_response_recorded is not None:
                if self.on_response_recorded_data is not None:
                    self.on_response_recorded(*((self.on_response_recorded_data) + (self.response,)))

        def get_response(self):
            return self.response

        @staticmethod
        def get_button_list(titles, dialog):
            blist = []
            for title in titles:
                blist.append(GUI.Button((0, 0), title, state.get_color_palette().get_color("item"),
                                        state.get_color_palette().get_color("background"), 18,
                                        width=dialog.container.width / len(titles), height=40,
                                        onClick=dialog.record_response, onClickData=(title,)))
            return blist

    class OKDialog(Dialog):
        def __init__(self, title, text, on_response_recorded=None, on_response_recorded_data=()):
            okbtn = GUI.Button((0, 0), "OK", state.get_color_palette().get_color("item"),
                               state.get_color_palette().get_color("background"), 18,
                               width=state.get_gui().width, height=40,
                               onClick=self.record_response, onClickData=("OK",))
            super(GUI.OKDialog, self).__init__(title, text, [okbtn], on_response_recorded)

    class ErrorDialog(Dialog):
        def __init__(self, text, on_response_recorded=None, on_response_recorded_data=()):
            okbtn = GUI.Button((0, 0), "Acknowledged", state.get_color_palette().get_color("item"),
                               state.get_color_palette().get_color("background"), 18,
                               width=state.get_gui().width, height=40, onClick=self.record_response,
                               onClickData=("Acknowledged",))
            super(GUI.ErrorDialog, self).__init__("Error", text, [okbtn], on_response_recorded)
            self.container.background_color = state.get_color_palette().get_color("error")

    class WarningDialog(Dialog):
        def __init__(self, text, on_response_recorded=None, on_response_recorded_data=()):
            okbtn = GUI.Button((0, 0), "OK", state.get_color_palette().get_color("item"),
                               state.get_color_palette().get_color("background"), 18,
                               width=state.get_gui().width, height=40,
                               onClick=self.record_response, onClickData=("OK",))
            super(GUI.WarningDialog, self).__init__("Warning", text, [okbtn], on_response_recorded)
            self.container.background_color = state.get_color_palette().get_color("warning")

    class YNDialog(Dialog):
        def __init__(self, title, text, on_response_recorded=None, on_response_recorded_data=()):
            ybtn = GUI.Button((0, 0), "Yes", (200, 250, 200), (50, 50, 50), 18,
                              width=(state.get_gui().width / 2), height=40, onClick=self.record_response,
                              onClickData=("Yes",))
            nbtn = GUI.Button((0, 0), "No", state.get_color_palette().get_color("item"),
                              state.get_color_palette().get_color("background"), 18,
                              width=(state.get_gui().width / 2), height=40, onClick=self.record_response,
                              onClickData=("No",))
            super(GUI.YNDialog, self).__init__(title, text, [ybtn, nbtn], on_response_recorded)
            self.on_response_recorded_data = on_response_recorded_data

    class OKCancelDialog(Dialog):
        def __init__(self, title, text, on_response_recorded=None, on_response_recorded_data=()):
            okbtn = GUI.Button((0, 0), "OK", state.get_color_palette().get_color("background"),
                               state.get_color_palette().get_color("item"), 18,
                               width=state.get_gui().width / 2, height=40, onClick=self.record_response,
                               onClickData=("OK",))
            cancbtn = GUI.Button((0, 0), "Cancel", state.get_color_palette().get_color("item"),
                                 state.get_color_palette().get_color("background"), 18,
                                 width=state.get_gui().width / 2, height=40, onClick=self.record_response,
                                 onClickData=("Cancel",))
            super(GUI.OKCancelDialog, self).__init__(title, text, [okbtn, cancbtn], on_response_recorded,
                                                     on_response_recorded_data)

    class AskDialog(Dialog):
        def __init__(self, title, text, on_response_recorded=None, on_response_recorded_data=()):
            okbtn = GUI.Button((0, 0), "OK", state.get_color_palette().get_color("background"),
                               state.get_color_palette().get_color("item"), 18,
                               width=state.get_gui().width / 2, height=40, onClick=self.return_recorded_response)
            cancelbtn = GUI.Button((0, 0), "Cancel", state.get_color_palette().get_color("item"),
                                   state.get_color_palette().get_color("background"), 18,
                                   width=state.get_gui().width / 2, height=40, onClick=self.record_response,
                                   onClickData=("Cancel",))
            super(GUI.AskDialog, self).__init__(title, text, [okbtn, cancelbtn], on_response_recorded,
                                                on_response_recorded_data)
            self.text_component.height -= 20
            self.text_component.refresh()
            self.text_entry_field = GUI.TextEntryField((0, 80), width=self.container.width, height=20)
            self.container.add_child(self.text_entry_field)

        def return_recorded_response(self):
            self.record_response(self.text_entry_field.get_text())

    class CustomContentDialog(Dialog):
        def __init__(self, title, custom_component, action_buttons, on_response_recorded=None, btn_pad=0, btn_margin=5,
                     **data):
            self.application = state.get_active_application()
            self.title = title
            self.response = None
            self.base_container = GUI.Container((0, 0), width=state.get_gui().width,
                                                height=state.get_active_application().ui.height, color=(0, 0, 0, 0.5))
            self.container = custom_component
            self.button_list = GUI.Dialog.get_button_list(action_buttons, self) if type(
                action_buttons[0]) == str else action_buttons
            self.button_row = GUI.ButtonRow((0, self.container.height - 33), width=self.container.width, height=40,
                                            color=(0, 0, 0, 0), padding=btn_pad, margin=btn_margin)
            for button in self.button_list:
                self.button_row.add_child(button)
            self.container.add_child(self.button_row)
            self.base_container.add_child(self.container)
            self.on_response_recorded = on_response_recorded
            self.data = data
            self.on_response_recorded_data = data.get("onResponseRecordedData", ())

    class NotificationMenu(Overlay):
        def __init__(self):
            super(GUI.NotificationMenu, self).__init__((40, 20), width=200, height=260, color=(20, 20, 20, 200))
            self.text = GUI.Text((1, 1), "Notifications", (200, 200, 200), 18)
            self.clear_all_btn = GUI.Button((self.width - 50, 0), "Clear", (200, 200, 200), (20, 20, 20), width=50,
                                            height=20, onClick=self.clear_all)
            self.n_container = GUI.ListScrollableContainer((0, 20), width=200, height=240, transparent=True, margin=5)
            self.add_child(self.text)
            self.add_child(self.clear_all_btn)
            self.add_child(self.n_container)
            self.refresh()

        def refresh(self):
            self.n_container.clear_children()
            for notification in state.get_notification_queue().notifications:
                self.n_container.add_child(notification.get_container())

        def display(self):
            self.refresh()
            state.get_notification_queue().new = False
            state.get_function_bar().clock_text.color = state.get_color_palette().get_color("accent")
            super(GUI.NotificationMenu, self).display()

        def clear_all(self):
            state.get_notification_queue().clear()
            self.refresh()

    class RecentAppSwitcher(Overlay):
        def __init__(self):
            super(GUI.RecentAppSwitcher, self).__init__((0, screen.get_height() - 100), height=60)
            self.container.border = 1
            self.container.border_color = state.get_color_palette().get_color("item")

        def populate(self):
            self.container.clear_children()
            self.recent_pages = GUI.PagedContainer((20, 0), width=self.width - 40, height=60, hideControls=True)
            self.recent_pages.add_page(self.recent_pages.generate_page())
            self.btn_left = GUI.Button((0, 0), "<", state.get_color_palette().get_color("accent"),
                                       state.get_color_palette().get_color("item"), 20, width=20, height=60,
                                       onClick=self.recent_pages.page_left)
            self.btn_right = GUI.Button((self.width - 20, 0), ">", state.get_color_palette().get_color("accent"),
                                        state.get_color_palette().get_color("item"), 20, width=20, height=60,
                                        onClick=self.recent_pages.page_right)
            per_app = (self.width - 40) / 4
            current = 0
            for app in state.get_application_list().active_applications:
                if app != state.get_active_application() and app.parameters.get("persist", True) and app.name != "home":
                    if current >= 4:
                        current = 0
                        self.recent_pages.add_page(self.recent_pages.generate_page())
                    cont = GUI.Container((per_app * current, 0), transparent=True, width=per_app, height=self.height,
                                         border=1, borderColor=state.get_color_palette().get_color("item"),
                                         onClick=self.activate, onClickData=(app,), onLongClick=self.close_ask,
                                         onLongClickData=(app,))
                    cont.skip_child_check = True
                    icon = app.get_icon()
                    if not icon:
                        icon = state.get_icons().get_loaded_icon("unknown")
                    img = GUI.Image((0, 5), surface=icon)
                    img.position[0] = GUI.get_centered_coordinates(img, cont)[0]
                    name = GUI.Text((0, 45), app.title, state.get_color_palette().get_color("item"), 10)
                    name.position[0] = GUI.get_centered_coordinates(name, cont)[0]
                    cont.add_child(img)
                    cont.add_child(name)
                    self.recent_pages.add_child(cont)
                    current += 1
            if len(self.recent_pages.get_page(0).child_components) == 0:
                notxt = GUI.Text((0, 0), "No Recent Apps", state.get_color_palette().get_color("item"), 16)
                notxt.position = GUI.get_centered_coordinates(notxt, self.recent_pages.get_page(0))
                self.recent_pages.add_child(notxt)
            self.recent_pages.goto_page()
            self.add_child(self.recent_pages)
            self.add_child(self.btn_left)
            self.add_child(self.btn_right)

        def display(self):
            self.populate()
            super(GUI.RecentAppSwitcher, self).display()

        def activate(self, app):
            self.hide()
            app.activate()

        def close_ask(self, app):
            GUI.YNDialog("Close", "Are you sure you want to close the app " + app.title + "?", self.close,
                         (app,)).display()

        def close(self, app, resp):
            if resp == "Yes":
                app.deactivate(False)
                self.hide()
                if state.get_active_application() == state.get_application_list().get_app("launcher"):
                    Application.full_close_current()

    class Selector(Container):
        def __init__(self, position, items, **data):
            self.on_value_changed = data.get("onValueChanged", Application.dummy)
            self.on_value_changed_data = data.get("onValueChangedData", ())
            self.overlay = GUI.Overlay((20, 20), width=state.get_gui().width - 40, height=state.get_gui().height - 80)
            self.overlay.container.border = 1
            self.scroller = GUI.ListScrollableContainer((0, 0), transparent=True, width=self.overlay.width,
                                                        height=self.overlay.height, scrollAmount=20)
            for comp in self.generate_item_sequence(items, 14, state.get_color_palette().get_color("item")):
                self.scroller.add_child(comp)
            self.overlay.add_child(self.scroller)
            super(GUI.Selector, self).__init__(position, **data)
            self.event_bindings["onClick"] = self.show_overlay
            self.event_data["onClick"] = ()
            self.text_color = data.get("textColor", state.get_color_palette().get_color("item"))
            self.items = items
            self.current_item = self.items[0]
            self.text_component = GUI.Text((0, 0), self.current_item, self.text_color, 14, onClick=self.show_overlay)
            self.text_component.set_position([2, GUI.get_centered_coordinates(self.text_component, self)[1]])
            self.add_child(self.text_component)

        def show_overlay(self):
            self.overlay.display()

        def generate_item_sequence(self, items, size=22, color=(0, 0, 0)):
            comps = []
            acc_height = 0
            for item in items:
                el_c = GUI.Container((0, acc_height), transparent=True, width=self.overlay.width, height=40,
                                     onClick=self.on_select, onClickData=(item,), border=1, borderColor=(20, 20, 20))
                elem = GUI.Text((2, 0), item, color, size,
                                onClick=self.on_select, onClickData=(item,))
                elem.position[1] = GUI.get_centered_coordinates(elem, el_c)[1]
                el_c.add_child(elem)
                el_c.skip_child_check = True
                comps.append(el_c)
                acc_height += el_c.height
            return comps

        def on_select(self, new_val):
            self.overlay.hide()
            self.current_item = new_val
            self.text_component.text = self.current_item
            self.text_component.refresh()
            self.on_value_changed(*(self.on_value_changed_data + (new_val,)))

        def render(self, larger_surface):
            super(GUI.Selector, self).render(larger_surface)
            pygame.draw.circle(
                larger_surface, state.get_color_palette().get_color("accent"),
                (self.position[0] + self.width - (self.height / 2) - 2, self.position[1] + (self.height / 2)),
                (self.height / 2) - 5)

        def get_clicked_child(self, mouse_event, offset_x=0, offset_y=0):
            if self.check_click(mouse_event, offset_x, offset_y):
                return self
            return None

        def get_value(self):
            return self.current_item


class ImmersionUI(object):
    def __init__(self, app):
        self.application = app
        self.method = getattr(self.application.module, self.application.parameters["immersive"])
        self.onExit = None

    def launch(self, resp):
        if resp == "Yes":
            self.method(*(self, screen))
            if self.onExit is not None:
                self.onExit()

    def start(self, on_exit=None):
        self.onExit = on_exit
        GUI.YNDialog("Fullscreen",
                     "The application " + self.application.title + " is requesting total control of the UI. Launch?",
                     self.launch).display()


class Application(object):
    @staticmethod
    def dummy(*args, **kwargs):
        pass

    @staticmethod
    def get_listings():
        listingsfile = open("apps/apps.json", "rU")
        app_listings = json.load(listingsfile)
        listingsfile.close()
        return app_listings

    @staticmethod
    def chain_refresh_current():
        if state.get_active_application() is not None:
            state.get_active_application().chain_refresh()

    @staticmethod
    def set_active_app(app="prev"):
        if app == "prev":
            app = state.get_application_list().get_most_recent_active()
        state.set_active_application(app)
        state.get_function_bar().app_title_text.set_text(state.get_active_application().title)
        state.get_gui().repaint()
        state.get_application_list().push_active_app(app)

    @staticmethod
    def full_close_app(app):
        app.deactivate(False)
        state.get_application_list().get_most_recent_active().activate(fromFullClose=True)

    @staticmethod
    def full_close_current():
        if state.get_active_application().name != "home":
            Application.full_close_app(state.get_active_application())

    @staticmethod
    def remove_listing(location):
        alist = Application.get_listings()
        try:
            del alist[location]
        except:
            print
        "The application listing for " + location + " could not be removed."
        listingsfile = open("apps/apps.json", "w")
        json.dump(alist, listingsfile)
        listingsfile.close()

    @staticmethod
    def install(packageloc):
        package = ZipFile(packageloc, "r")
        package.extract("app.json", "temp/")
        app_listing = open("temp/app.json", "rU")
        app_info = json.loads(str(unicode(app_listing.read(), errors="ignore")))
        app_listing.close()
        app_name = str(app_info.get("name"))
        if app_name not in state.get_application_list().get_application_list():
            os.mkdir(os.path.join("apps/", app_name))
        else:
            print
            "Upgrading " + app_name
        package.extractall(os.path.join("apps/", app_name))
        package.close()
        alist = Application.get_listings()
        alist[os.path.join("apps/", app_name)] = app_name
        listingsfile = open("apps/apps.json", "w")
        json.dump(alist, listingsfile)
        listingsfile.close()
        return app_name

    @staticmethod
    def register_debug_app_ask():
        state.get_application_list().get_app("files").getModule().FolderPicker((10, 10), width=220, height=260,
                                                                               onSelect=Application.register_debug_app,
                                                                               startFolder="apps/").display()

    @staticmethod
    def register_debug_app(path):
        app_listing = open(os.path.join(path, "app.json"), "rU")
        app_info = json.loads(str(unicode(app_listing.read(), errors="ignore")))
        app_listing.close()
        app_name = str(app_info.get("name"))
        alist = Application.get_listings()
        alist[os.path.join("apps/", app_name)] = app_name
        listingsfile = open("apps/apps.json", "w")
        json.dump(alist, listingsfile)
        listingsfile.close()
        state.get_application_list().reload_list()
        GUI.OKDialog("Registered", "The application from " + path + " has been registered on the system.").display()

    def __init__(self, location):
        self.parameters = {}
        self.location = location
        infofile = open(os.path.join(location, "app.json").replace("\\", "/"), "rU")
        app_data = json.loads(str(unicode(infofile.read(), errors="ignore")))
        self.name = str(app_data.get("name"))
        self.title = str(app_data.get("title", self.name))
        self.version = float(app_data.get("version", 0.0))
        self.author = str(app_data.get("author", "No Author"))
        self.module = import_module("apps." + str(app_data.get("module", self.name)), "apps")
        self.module.state = state
        self.file = None
        try:
            self.main_method = getattr(self.module, str(app_data.get("main")))
        except:
            self.main_method = Application.dummy
        try:
            self.parameters = app_data.get("more")
        except:
            pass
        self.description = app_data.get("description", "No Description.")
        # Immersion check
        if "immersive" in self.parameters:
            self.immersion_ui = ImmersionUI(self)
        else:
            self.immersion_ui = None
        # check for and load event handlers
        self.evt_handlers = {}
        if "onStart" in self.parameters:
            self.evt_handlers["onStartReal"] = self.parameters["onStart"]
        self.evt_handlers["onStart"] = [self.on_start, ()]
        if "onStop" in self.parameters:
            self.evt_handlers["onStop"] = getattr(self.module, self.parameters["onStop"])
        if "onPause" in self.parameters:
            self.evt_handlers["onPause"] = getattr(self.module, self.parameters["onPause"])
        if "onResume" in self.parameters:
            self.evt_handlers["onResume"] = getattr(self.module,
                                                    self.parameters["onResume"])
        if "onCustom" in self.parameters:
            self.evt_handlers["onCustom"] = getattr(self.module,
                                                    self.parameters["onCustom"])
        self.thread = Thread(self.main_method, **self.evt_handlers)
        self.ui = GUI.AppContainer(self)
        self.dataStore = DataStore(self)
        infofile.close()
        self.thread = Thread(self.main_method, **self.evt_handlers)

    def get_module(self):
        return self.module

    def chain_refresh(self):
        self.ui.refresh()

    def on_start(self):
        self.load_color_scheme()
        if "onStartReal" in self.evt_handlers and not self.evt_handlers.get("onStartBlock", False):
            getattr(self.module, self.evt_handlers["onStartReal"])(state, self)
        if self.evt_handlers.get("onStartBlock", False):
            self.evt_handlers["onStartBlock"] = False

    def load_color_scheme(self):
        if "colorScheme" in self.parameters:
            state.get_color_palette().set_scheme(self.parameters["colorScheme"])
        else:
            state.get_color_palette().set_scheme()
        self.ui.background_color = state.get_color_palette().get_color("background")
        self.ui.refresh()

    def activate(self, **data):
        try:
            if data.get("noOnStart", False):
                self.evt_handlers["onStartBlock"] = True
            if state.get_active_application() == self:
                return
            if (state.get_application_list().get_most_recent_active() is not None and
                    not data.get("fromFullClose", False)):
                state.get_application_list().get_most_recent_active().deactivate()
            Application.set_active_app(self)
            self.load_color_scheme()
            if self.thread in state.get_thread_controller().threads:
                self.thread.set_pause(False)
            else:
                if self.thread.stop:
                    self.thread = Thread(self.main_method, **self.evt_handlers)
                state.get_thread_controller().add_thread(self.thread)
        except:
            State.error_recovery("Application init error.", "App name: " + self.name)

    def get_icon(self):
        if "icon" in self.parameters:
            if self.parameters["icon"] is None:
                return False
            return state.get_icons().get_loaded_icon(self.parameters["icon"], self.location)
        else:
            return state.get_icons().get_loaded_icon("unknown")

    def deactivate(self, pause=True):
        if "persist" in self.parameters:
            if self.parameters["persist"] == False:
                pause = False
        if pause:
            self.thread.set_pause(True)
        else:
            self.ui.clear_children()
            self.thread.set_stop()
            state.get_application_list().close_app(self)
        state.get_color_palette().set_scheme()

    def uninstall(self):
        rmtree(self.location, True)
        Application.remove_listing(self.location)


class ApplicationList(object):
    def __init__(self):
        self.applications = {}
        self.active_applications = []
        applist = Application.get_listings()
        for key in dict(applist).keys():
            try:
                self.applications[applist.get(key)] = Application(key)
            except:
                State.error_recovery("App init error: " + key, "NoAppDump")

    def get_app(self, name):
        if name in self.applications:
            return self.applications[name]
        else:
            return None

    def get_application_list(self):
        return self.applications.values()

    def push_active_app(self, app):
        if app not in self.active_applications:
            self.active_applications.insert(0, app)
        else:
            self.switch_last(app)

    def close_app(self, app=None):
        if app is None:
            if len(self.active_applications) > 1:
                return self.active_applications.pop(0)
        self.active_applications.remove(app)

    def switch_last(self, app):
        if app is None:
            return
        self.active_applications = [self.active_applications.pop(
            self.active_applications.index(app))] + self.active_applications

    def get_most_recent_active(self):
        if len(self.active_applications) > 0:
            return self.active_applications[0]

    def get_previous_active(self):
        if len(self.active_applications) > 1:
            return self.active_applications[1]

    def reload_list(self):
        applist = Application.get_listings()
        for key in dict(applist).keys():
            if applist.get(key) not in self.applications.keys():
                try:
                    self.applications[applist.get(key)] = Application(key)
                except:
                    State.error_recovery("App init error: " + key, "NoAppDump")
        for key in self.applications.keys():
            if key not in applist.values():
                del self.applications[key]


class Notification(object):
    def __init__(self, title, text, **data):
        self.title = title
        self.text = text
        self.active = True
        self.source = data.get("source", None)
        self.image = data.get("image", None)
        if self.source is not None:
            self.onSelectedMethod = data.get("onSelected", self.source.activate)
        else:
            self.onSelectedMethod = data.get("onSelected", Application.dummy)
        self.onSelectedData = data.get("onSelectedData", ())

    def on_selected(self):
        self.clear()
        state.get_function_bar().toggle_notification_nenu()
        self.onSelectedMethod(*self.onSelectedData)

    def clear(self):
        self.active = False
        state.get_notification_queue().sweep()
        state.get_function_bar().notificationMenu.refresh()

    def get_container(self, c_width=200, c_height=40):
        cont = GUI.Container((0, 0), width=c_width, height=c_height, transparent=True, onClick=self.on_selected,
                             onLongClick=self.clear)
        if self.image is not None:
            try:
                self.image.set_position([0, 0])
                cont.add_child(self.image)
            except:
                if isinstance(self.image, pygame.Surface):
                    self.image = GUI.Image((0, 0), surface=self.image, onClick=self.on_selected)
                else:
                    self.image = GUI.Image((0, 0), path=self.image, onClick=self.on_selected)
        else:
            self.image = GUI.Image(
                (0, 0), surface=state.get_icons().get_loaded_icon("unknown"), onClick=self.on_selected,
                onLongClick=self.clear)
        rtitle = GUI.Text((41, 0), self.title, (200, 200, 200), 20, onClick=self.on_selected, onLongClick=self.clear)
        rtxt = GUI.Text((41, 24), self.text, (200, 200, 200), 14, onClick=self.on_selected, onLongClick=self.clear)
        cont.add_child(self.image)
        cont.add_child(rtitle)
        cont.add_child(rtxt)
        return cont


class PermanentNotification(Notification):
    def clear(self):
        pass

    def force_clear(self):
        super(PermanentNotification, self).clear()


class NotificationQueue(object):
    def __init__(self):
        self.notifications = []
        self.new = False

    def sweep(self):
        for notification in self.notifications:
            if not notification.active:
                self.notifications.remove(notification)

    def push(self, notification):
        self.notifications.insert(0, notification)
        self.new = True

    def clear(self):
        self.notifications = []


class DataStore(object):
    def __init__(self, app):
        self.application = app
        self.dsPath = os.path.join("res/", app.name + ".ds")

    def get_store(self):
        if not os.path.exists(self.dsPath):
            wf = open(self.dsPath, "w")
            json.dump({"dsApp": self.application.name}, wf)
            wf.close()
        rf = open(self.dsPath, "rU")
        self.data = json.loads(str(unicode(rf.read(), errors="ignore")))
        rf.close()
        return self.data

    def save_store(self):
        wf = open(self.dsPath, "w")
        json.dump(self.data, wf)
        wf.close()

    def get(self, key, default=None):
        return self.get_store().get(key, default)

    def set(self, key, value):
        self.data[key] = value
        self.save_store()

    def __getitem__(self, itm):
        return self.get(itm)

    def __setitem__(self, key, val):
        self.set(key, val)


class State(object):
    def __init__(self, active_app=None, colors=None, icons=None, controller=None, event_queue=None,
                 notification_queue=None, functionbar=None, font=None, t_font=None, gui=None, app_list=None,
                 keyboard=None):
        self.active_application = active_app
        self.color_palette = colors
        self.icons = icons
        self.thread_controller = controller
        self.event_queue = event_queue
        self.notification_queue = notification_queue
        self.function_bar = functionbar
        self.font = font
        self.typing_font = t_font
        self.app_list = app_list
        self.keyboard = keyboard
        self.recent_app_switcher = None
        if gui is None:
            self.gui = GUI()
        if colors is None:
            self.color_palette = GUI.ColorPalette()
        if icons is None:
            self.icons = GUI.Icons()
        if controller is None:
            self.thread_controller = Controller()
        if event_queue is None:
            self.event_queue = GUI.EventQueue()
        if notification_queue is None:
            self.notification_queue = NotificationQueue()
        if font is None:
            self.font = GUI.Font()
        if t_font is None:
            self.typing_font = GUI.Font("res/RobotoMono-Regular.ttf")

    def get_active_application(self):
        return self.active_application

    def get_color_palette(self):
        return self.color_palette

    def get_icons(self):
        return self.icons

    def get_thread_controller(self):
        return self.thread_controller

    def get_event_queue(self):
        return self.event_queue

    def get_notification_queue(self):
        return self.notification_queue

    def get_font(self):
        return self.font

    def get_typing_font(self):
        return self.typing_font

    def get_gui(self):
        return self.gui

    def get_application_list(self):
        if self.app_list is None:
            self.app_list = ApplicationList()
        return self.app_list

    def get_function_bar(self):
        if self.function_bar is None:
            self.function_bar = GUI.FunctionBar()
        return self.function_bar

    def get_keyboard(self):
        return self.keyboard

    def set_active_application(self, app):
        self.active_application = app

    def set_color_palette(self, colors):
        self.color_palette = colors

    def set_icons(self, icons):
        self.icons = icons

    def set_thread_controller(self, controller):
        self.thread_controller = controller

    def set_event_queue(self, queue):
        self.event_queue = queue

    def set_notification_queue(self, queue):
        self.notification_queue = queue

    def set_function_bar(self, bar):
        self.function_bar = bar

    def set_font(self, font):
        self.font = font

    def set_typing_font(self, tfont):
        self.typing_font = tfont

    def set_gui(self, gui):
        self.gui = gui

    def set_application_list(self, app_list):
        self.app_list = app_list

    def set_keyboard(self, keyboard):
        self.keyboard = keyboard

    @staticmethod
    def get_state():
        return state

    @staticmethod
    def exit():
        state.get_thread_controller().stop_all_threads()
        pygame.quit()
        os.exit(1)

    @staticmethod
    def rescue():
        global state
        r_fnt = pygame.font.Font(None, 16)
        r_clock = pygame.time.Clock()
        state.get_notification_queue().clear()
        state.get_event_queue().clear()
        print
        "Recovery menu entered."
        while True:
            r_clock.tick(10)
            screen.fill([0, 0, 0])
            pygame.draw.rect(screen, [200, 200, 200], [0, 0, 280, 80])
            screen.blit(r_fnt.render("Return to Python OS", 1, [20, 20, 20]), [40, 35])
            pygame.draw.rect(screen, [20, 200, 20], [0, 80, 280, 80])
            screen.blit(r_fnt.render("Stop all apps and return", 1, [20, 20, 20]), [40, 115])
            pygame.draw.rect(screen, [20, 20, 200], [0, 160, 280, 80])
            screen.blit(r_fnt.render("Stop current app and return", 1, [20, 20, 20]), [40, 195])
            pygame.draw.rect(screen, [200, 20, 20], [0, 240, 280, 80])
            screen.blit(r_fnt.render("Exit completely", 1, [20, 20, 20]), [40, 275])
            pygame.display.flip()
            for evt in pygame.event.get():
                if evt.type == pygame.QUIT or evt.type == pygame.KEYDOWN and evt.key == pygame.K_ESCAPE:
                    print
                    "Quit signal detected."
                    try:
                        state.exit()
                    except:
                        pygame.quit()
                        exit()
                if evt.type == pygame.MOUSEBUTTONDOWN:
                    if evt.pos[1] >= 80:
                        if evt.pos[1] >= 160:
                            if evt.pos[1] >= 240:
                                print
                                "Exiting."
                                try:
                                    state.exit()
                                except:
                                    pygame.quit()
                                    exit()
                            else:
                                print
                                "Stopping current app"
                                try:
                                    Application.full_close_current()
                                except:
                                    print
                                    "Regular stop failed!"
                                    Application.set_active_app(state.get_application_list().get_app("home"))
                                return
                        else:
                            print
                            "Closing all active applications"
                            for a in state.get_application_list().active_applications:
                                try:
                                    a.deactivate()
                                except:
                                    print
                                    "The app " + str(a.name) + " failed to deactivate!"
                                    state.get_application_list().active_applications.remove(a)
                            state.get_application_list().get_app("home").activate()
                            return
                    else:
                        print
                        "Returning to Python OS."
                        return

    @staticmethod
    def error_recovery(message="Unknown", data=None):
        print
        message
        screen.fill([200, 100, 100])
        rf = pygame.font.Font(None, 24)
        sf = pygame.font.Font(None, 18)
        screen.blit(rf.render("Failure detected.", 1, (200, 200, 200)), [20, 20])
        open_apps = (
            str([
                    a.name for a in state.get_application_list().active_applications
                ]) if data != "NoAppDump" else "Not Yet Initialized")
        f = open("temp/last_error.txt", "w")
        txt = "Python OS 6 Error Report\nTIME: " + str(datetime.now())
        txt += "\n\nOpen Applications: " + open_apps
        txt += "\nMessage: " + message
        txt += "\nAdditional Data:\n"
        txt += str(data)
        txt += "\n\nTraceback:\n"
        txt += format_exc()
        f.write(txt)
        f.close()
        screen.blit(sf.render("Traceback saved.", 1, (200, 200, 200)), [20, 80])
        screen.blit(sf.render("Location: temp/last_error.txt", 1, (200, 200, 200)), [20, 100])
        screen.blit(sf.render("Message:", 1, (200, 200, 200)), [20, 140])
        screen.blit(sf.render(message, 1, (200, 200, 200)), [20, 160])
        pygame.draw.rect(screen, [200, 200, 200], [0, 280, 240, 40])
        screen.blit(sf.render("Return to Python OS", 1, (20, 20, 20)), [20, 292])
        pygame.draw.rect(screen, [50, 50, 50], [0, 240, 240, 40])
        screen.blit(sf.render("Open Recovery Menu", 1, (200, 200, 200)), [20, 252])
        r_clock = pygame.time.Clock()
        pygame.display.flip()
        while True:
            r_clock.tick(10)
            for evt in pygame.event.get():
                if evt.type == pygame.QUIT or evt.type == pygame.KEYDOWN and evt.key == pygame.K_ESCAPE:
                    try:
                        state.exit()
                    except:
                        pygame.quit()
                        exit()
                if evt.type == pygame.MOUSEBUTTONDOWN:
                    if evt.pos[1] >= 280:
                        return
                    elif evt.pos[1] >= 240:
                        State.rescue()
                        return

    @staticmethod
    def main():
        while True:
            # Limit FPS
            state.get_gui().timer.tick(state.get_gui().update_interval)
            state.get_gui().monitor_fps()
            # Update event queue
            state.get_event_queue().check()
            # Refresh main thread controller
            state.get_thread_controller().run()
            # Paint UI
            if state.get_active_application() is not None:
                try:
                    state.get_active_application().ui.render()
                except:
                    State.error_recovery("UI error.", "FPS: " + str(state.get_gui().update_interval))
                    Application.full_close_current()
            state.get_function_bar().render()
            if state.get_keyboard() is not None and state.get_keyboard().active:
                state.get_keyboard().render(screen)

            if state.get_gui().update_interval <= 5:
                pygame.draw.rect(screen, (255, 0, 0), [state.get_gui().width - 5, 0, 5, 5])

            state.get_gui().refresh()
            # Check Events
            latest_event = state.get_event_queue().get_latest_complete()
            if latest_event is not None:
                clicked_child = None
                if state.get_keyboard() is not None and state.get_keyboard().active:
                    if latest_event.pos[1] < state.get_keyboard().base_container.position[1]:
                        if state.get_active_application().ui.get_clicked_child(
                                latest_event) == state.get_keyboard().text_entry_field:
                            state.get_keyboard().text_entry_field.on_click()
                        else:
                            state.get_keyboard().deactivate()
                        continue
                    clicked_child = state.get_keyboard().base_container.get_clicked_child(latest_event)
                    if clicked_child is None:
                        clicked_child = state.get_active_application().ui.get_clicked_child(latest_event)
                    if (clicked_child is None and state.get_keyboard().text_entry_field.position == [0, 0] and
                            state.get_keyboard().text_entry_field.check_click(latest_event)):
                        clicked_child = state.get_keyboard().text_entry_field
                else:
                    if latest_event.pos[1] < state.get_gui().height - 40:
                        if state.get_active_application() is not None:
                            clicked_child = state.get_active_application().ui.get_clicked_child(latest_event)
                    else:
                        clicked_child = state.get_function_bar().container.get_clicked_child(latest_event)
                if clicked_child is not None:
                    try:
                        if isinstance(latest_event, GUI.LongClickEvent):
                            clicked_child.on_long_click()
                        else:
                            if isinstance(latest_event, GUI.IntermediateUpdateEvent):
                                clicked_child.on_intermediate_update()
                            else:
                                clicked_child.on_click()
                    except:
                        State.error_recovery("Event execution error", "Click event: " + str(latest_event))

    @staticmethod
    def state_shell():
        # For debugging purposes only. Do not use in actual code!
        print
        "Python OS 6 State Shell. Type \"exit\" to quit."
        user_input = raw_input("S> ")
        while user_input != "exit":
            if not user_input.startswith("state.") and user_input.find("Static") == -1:
                if user_input.startswith("."):
                    user_input = "state" + user_input
                else:
                    user_input = "state." + user_input
            print
            eval(user_input, {"state": state, "Static": State})
            user_input = raw_input("S> ")
        State.exit(True)


if __name__ == "__main__":
    state = State()
    globals()["state"] = state
    __builtin__.state = state
    # TEST
    # State.state_shell()
    if __import__("sys").platform == 'linux2':
        pygame.mouse.set_visible(False)
    state.get_application_list().get_app("home").activate()
    try:
        State.main()
    except:
        State.error_recovery("Fatal system error.")
