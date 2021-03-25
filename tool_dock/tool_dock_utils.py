import collections
import importlib
import inspect
import os
import runpy
import sys
from functools import partial

from tool_dock.ui import parameter_grid
from tool_dock.ui import ui_utils
from tool_dock.ui.ui_utils import QtCore, QtWidgets

PY_2 = sys.version_info[0] < 3
background_form = "background-color:rgb({0}, {1}, {2})"


class RequiresValueType(object):
    """Used to mark whether arguments have a default value specified"""
    pass


class LocalConstants(object):
    # generate custom py scripts from folder
    dynamic_classes_generated = False
    dynamic_classes = {}

    env_extra_modules = "TOOL_DOCK_EXTRA_MODULES"
    env_script_folders = "TOOL_DOCK_SCRIPT_FOLDERS"

    # a base scripts folder can be defined via this environment variable
    # script files in this folder structure will be added as dynamic classes
    script_folders = os.environ.get(env_script_folders, "D:/Google Drive/Scripting/_Scrsipts")

    def generate_dynamic_classes(self):
        if not self.script_folders:
            return

        for script_folder in self.script_folders.split(";"):
            if not script_folder:  # ignore empty strings
                continue

            if not os.path.exists(script_folder):
                continue

            self.dynamic_classes_from_script_folder(script_folder)

        if len(self.dynamic_classes.keys()) > 0:
            print("Generated: {} tool classes from files in: {}".format(len(self.dynamic_classes), self.script_folders))

        self.dynamic_classes_generated = True

    def dynamic_classes_from_script_folder(self, script_folder):
        """Find all scripts in folder structure and add them as tool classes"""
        for script_path in get_paths_in_folder(script_folder, extension_filter=".py"):
            self.dynamic_class_from_script(script_path)

    # for dynamic class creation in custom modules
    def dynamic_class_from_script(self, script_path):
        script_name = os.path.splitext(os.path.basename(script_path))[0]
        if script_name in self.dynamic_classes.keys():
            return

        script_cls = make_class_from_script(script_path, tool_name=script_name)

        self.dynamic_classes[script_name] = script_cls

        return script_cls


lk = LocalConstants()


class _InternalToolDockItemBase(QtWidgets.QWidget):
    """
    Internal Base Class for tools logic
    """
    TOOL_NAME = "TOOL"
    TOOL_TIP = "TOOLTIP UNDEFINED"
    BACKGROUND_COLOR = None

    SCRIPT_PATH = None  # used by dynamically generated classes

    def __init__(self, *args, **kwargs):
        super(_InternalToolDockItemBase, self).__init__(*args, **kwargs)

        self.main_layout = QtWidgets.QHBoxLayout()
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(self.main_layout)

        # right click menu
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.open_context_menu)
        self.context_menu_actions = [
            {"Set Splitter - Vertical": partial(self.set_splitter_orientation, True)},
            {"Set Splitter - Horizontal": partial(self.set_splitter_orientation, False)},
        ]

        # if multiple actions defined for Tool
        self._tool_actions = self.get_tool_actions()
        self._parameters_auto_generated = False

        # Splitter between parameter_grid and 'run' buttons
        self.main_splitter = QtWidgets.QSplitter()

        # parameter grid
        self.param_grid = parameter_grid.ParameterGrid()
        self.param_grid.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        self.main_splitter.addWidget(self.param_grid)

        # build run buttons and add to splitter
        ui_widget = self.build_ui_widget()
        if self.BACKGROUND_COLOR:
            ui_widget.setStyleSheet(background_form.format(*self.BACKGROUND_COLOR))
        self.main_splitter.addWidget(ui_widget)

        # default hide parameter grid
        self.main_splitter.handle(1).setEnabled(False)
        self.main_splitter.setSizes([0, 100])
        self.main_layout.addWidget(self.main_splitter)

    def open_context_menu(self):
        return ui_utils.build_menu_from_action_list(self.context_menu_actions)

    def auto_populate_parameters(self):
        """Convenience function for generating parameters based on arguments of 'run'"""
        run_arguments = get_func_arguments(self.run)

        if not run_arguments:
            return

        for param_name, default_value in run_arguments.items():
            if param_name == "self":  # ignore 'self' argument, should be safe-ish
                run_arguments.pop(param_name)
                continue

            is_required = default_value == RequiresValueType
            if is_required:
                run_arguments[param_name] = str()  # fill to make sure every argument has something

        if run_arguments:
            self.param_grid.from_data(run_arguments)
            self._parameters_auto_generated = True

    def set_splitter_orientation(self, vertical=True):
        orientation = QtCore.Qt.Vertical if vertical else QtCore.Qt.Horizontal
        self.main_splitter.setOrientation(orientation)

    def post_init(self):
        # auto generate parameter widgets if run function has arguments
        # skip if parameters have been manually defined
        if not self.param_grid.parameters:
            self.auto_populate_parameters()

        # show parameter grid if parameters are defined
        if self.param_grid.parameters:
            self.main_splitter.handle(1).setEnabled(True)
            self.main_splitter.setSizes([sys.maxint, sys.maxint])

    def build_ui_widget(self):
        """
        Create buttons to execute run function
        Can be overridden by subclasses
        :return:
        """
        if self._tool_actions:
            multi_button_layout = QtWidgets.QHBoxLayout()
            multi_button_layout.setContentsMargins(0, 0, 0, 0)
            for name, func in self._tool_actions.items():
                btn = QtWidgets.QPushButton(name)
                btn.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.MinimumExpanding)

                btn.clicked.connect(partial(self._run, func))
                multi_button_layout.addWidget(btn)

            multi_button_widget = QtWidgets.QWidget()
            multi_button_widget.setLayout(multi_button_layout)
            main_widget = multi_button_widget
        else:
            btn = QtWidgets.QPushButton("{}".format(self.TOOL_NAME))
            btn.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.MinimumExpanding)
            btn.clicked.connect(self._run)
            main_widget = btn
        return main_widget

    def _run(self, func=None):
        kwargs = {}  # maybe put something in here by default? not sure
        if func:
            func(**kwargs)
        else:
            if self._parameters_auto_generated:
                kwargs = self.param_grid.as_data()
            self.run(**kwargs)

    # to overwrite
    def run(self, *args, **kwargs):
        print("'run' not implemented: {}".format(self.TOOL_NAME))

    def get_tool_actions(self):
        return {}


class ToolDockItemBase(_InternalToolDockItemBase):
    """
    Base Class for tools to inherit from
    """
    pass


class ToolDockSettings(QtCore.QSettings):
    def __init__(self, *args, **kwargs):
        super(ToolDockSettings, self).__init__(*args, **kwargs)

    def get_value(self, key, default=None):
        data_type = None
        if default is not None:
            data_type = type(default)

        settings_val = self.value(key, defaultValue=default)

        # safety convert bool to proper type
        if data_type == bool:
            settings_val = True if settings_val in ("true", "True", "1", 1, True) else False

        return settings_val


def import_extra_modules(refresh=False):
    modules_to_import = os.environ.get(lk.env_extra_modules, "").split(";")

    if refresh:
        for mod_key in sys.modules.keys():
            for module_import_str in modules_to_import:

                if not module_import_str:  # skip empty strings
                    continue

                # pop up out all submodule of imported module
                if module_import_str in mod_key:
                    sys.modules.pop(mod_key)
                    print "popping", mod_key
                    continue

    # import modules defined in environment variable
    for module_import_str in modules_to_import:
        if module_import_str:  # if not an empty string
            print "importing", module_import_str
            importlib.import_module(module_import_str)


def get_func_arguments(func):
    """ copied from https://github.com/rBrenick/argument-dialog """
    if PY_2:
        arg_spec = inspect.getargspec(func)
    else:
        arg_spec = inspect.getfullargspec(func)

    parameter_dict = collections.OrderedDict()
    for param_name in arg_spec.args:
        parameter_dict[param_name] = RequiresValueType  # argument has no default value, not even a 'None'

    if arg_spec.defaults:
        for param_value, param_key in zip(arg_spec.defaults[::-1], reversed(parameter_dict.keys())):  # fill in defaults
            parameter_dict[param_key] = param_value

    return parameter_dict


def all_subclasses(cls):
    return set(cls.__subclasses__()).union([s for c in cls.__subclasses__() for s in all_subclasses(c)])


def get_tool_classes():
    if not lk.dynamic_classes_generated:
        lk.generate_dynamic_classes()

    # get all base sub classes
    subclasses = list(all_subclasses(ToolDockItemBase))
    subclasses.extend(lk.dynamic_classes.values())
    return subclasses


def get_preview_from_script(script_path, max_line_count=None):
    """
    Open file and read a couple of lines
    :param script_path: script file path
    :type script_path: str
    :param max_line_count: truncate preview to a certain line count
    :type max_line_count: int
    :return:
    """
    with open(script_path, "r") as fp:
        script_lines = fp.readlines()

    if max_line_count is None:
        max_line_count = len(script_lines)

    script_code = "".join(script_lines[:max_line_count])
    if len(script_lines) > max_line_count:
        script_code = "{}......".format(script_code)  # indicators that script is truncated

    preview_str = "{}\n\n{}\n".format(script_path, script_code)
    return preview_str


def make_class_from_script(script_path, tool_name):
    class DynamicClass(_InternalToolDockItemBase):
        TOOL_NAME = tool_name
        TOOL_TIP = script_path
        SCRIPT_PATH = script_path

        def run(self):
            return runpy.run_path(script_path, init_globals=globals(), run_name="__main__")

    return DynamicClass


def get_paths_in_folder(root_folder, extension_filter=""):
    for folder, _, file_names in os.walk(root_folder):
        for file_name in file_names:
            if file_name.endswith(extension_filter):
                yield os.path.join(folder, file_name)


def browse_for_settings_path(save=False):
    dialog = QtWidgets.QFileDialog(ui_utils.get_app_window())
    dialog.setNameFilter("*.ini")

    if save:
        dialog.setAcceptMode(dialog.AcceptSave)
    else:
        dialog.setAcceptMode(dialog.AcceptOpen)

    if dialog.exec_() == QtWidgets.QDialog.Accepted:
        return dialog.selectedFiles()[0]


def save_tooldock_settings(settings, current_tooldock, settings_path=None):
    """
    Save settings for current tooldock to standalone file for loading and saving

    :param settings:
    :param current_tooldock:
    :param settings_path:
    :return:
    """
    if settings_path is None:
        settings_path = browse_for_settings_path()

    if not settings_path:
        return

    out_settings = ToolDockSettings(settings_path, QtCore.QSettings.IniFormat)

    for setting_key in settings.allKeys():  # type: str
        if not setting_key.startswith(current_tooldock):
            continue
        out_settings.setValue(setting_key, settings.get_value(setting_key))

    out_settings.setValue("tooldock", current_tooldock)
    return settings_path


def load_tooldock_settings(target_settings=None, target_tooldock="", source_settings=None):
    """
    Load tooldock settings from standalone file into the target_settings

    :param target_settings:
    :param target_tooldock:
    :param source_settings:
    :return:
    """
    if source_settings is None:
        source_settings = browse_for_settings_path()

    if not source_settings:
        return

    if not isinstance(source_settings, ToolDockSettings):
        source_settings = ToolDockSettings(source_settings, QtCore.QSettings.IniFormat)

    settings_tooldock = source_settings.get_value("tooldock")

    for setting_key in source_settings.allKeys():  # type: str
        if not setting_key.startswith(settings_tooldock):
            continue

        # save data in current tooldock
        key = setting_key.replace(settings_tooldock, target_tooldock)

        target_settings.setValue(key, source_settings.get_value(setting_key))

    return True
