import atexit
import os
import readline
import sys
import subprocess
import typing
import abc
from concurrent.futures.thread import ThreadPoolExecutor


class ForwardToExecutorException(Exception):

    def __init__(self, commands: typing.List[str], *args: object) -> None:
        super().__init__(*args)
        self.commands = commands


class CommandNotFoundException(Exception):

    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class AbstractCommandExecutor(abc.ABC):

    def __init__(self) -> None:
        super().__init__()

    @abc.abstractmethod
    async def run(self, command_line: str) -> None:
        pass


class BuiltInCommandExecutor(AbstractCommandExecutor):

    def __init__(self) -> None:
        super().__init__()
        self.__built_in_cmd: dict[str, typing.Callable[[str], None]] = {
            "clear()": self.__clear,
            "exit()": self.__exit
        }

    def __clear(self, source: str) -> None:
        cmd = 'clear'
        if os.name == 'nt':
            cmd = 'cls'

        os.system(cmd)

    def __exit(self, source: str) -> None:
        raise KeyboardInterrupt()

    async def run(self, source: str) -> None:
        try:
            func = self.__built_in_cmd[source]
            func(source)
        except KeyError:
            raise CommandNotFoundException(source)


class ShellCommandExecutor(AbstractCommandExecutor):

    def __init__(self) -> None:
        super().__init__()

    async def run(self, command_line: str) -> None:
        with subprocess.Popen(command_line, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
            with ThreadPoolExecutor(max_workers=2) as executor:
                executor.submit(ShellCommandExecutor.__process_stdout, process)
                executor.submit(ShellCommandExecutor.__process_stderr, process)
            

    @staticmethod
    def __process_stdout(process: subprocess.Popen):
        for line in process.stdout:
                print(line.decode('utf8'), file=sys.stdout, end='')

    @staticmethod
    def __process_stderr(process: subprocess.Popen):
        for line in process.stderr:
                print(line.decode('utf8'), file=sys.stderr, end='')


class ChainCommandExecutor(AbstractCommandExecutor):

    def __init__(self, include_default_executors: bool = True, executors: typing.List[AbstractCommandExecutor] | None = None) -> None:
        super().__init__()
        self.__executors = []

        if include_default_executors:
            self.__executors.append(BuiltInCommandExecutor())

        if executors is not None:
            self.__executors.extend(executors)

        if include_default_executors:
            self.__executors.append(ShellCommandExecutor())

    async def run(self, command_line: str) -> None:
        command_executed = False

        for executor in self.__executors:
            try:
                await executor.run(command_line)
                command_executed = True
                break
            except CommandNotFoundException:
                pass

        if not command_executed:
            raise CommandNotFoundException(command_line)


class InteractiveConsole:

    def __init__(self, command_executor: AbstractCommandExecutor | None = None) -> None:
        self.__prompt_new = '>> '
        self.__prompt_continue = '.. '
        self.__continue_input = False
        self.__resetbuffer()
        self.__init_history()
        self.__executor = ChainCommandExecutor() if command_executor is None else command_executor

    def __init_history(self) -> None:
        histfile = os.path.expanduser("~/.console-history")
        readline.parse_and_bind("tab: complete")
        if hasattr(readline, "read_history_file"):
            try:
                readline.read_history_file(histfile)
            except FileNotFoundError:
                pass
            atexit.register(self.__save_history, histfile)

    def __save_history(self, histfile):
        readline.set_history_length(2000)
        readline.write_history_file(histfile)

    def __resetbuffer(self):
        self.__buffer = []
        self.__continue_input = False

    async def __run_executor(self, line: str):
        try:
            await self.__executor.run(line)
        except ForwardToExecutorException as ex:
            for command in ex.commands:
                readline.add_history(command)
                print(self.__prompt_new + command)
                await self.__run_executor(command)

    async def __run_command(self, line: str):
        more = False
        if line.endswith(' \\'):
            line = line[:-2]
            more = True
        self.__buffer.append(line)
        if not more:
            source = "\n".join(self.__buffer)
            await self.__run_executor(source)
            self.__resetbuffer()
        
        self.__continue_input = more

    def __write(self, data: str):
        print(data, file=sys.stderr)

    async def interact(self, exitmsg: str | None = None):
        while True:
            try:
                prompt = self.__prompt_continue if self.__continue_input else self.__prompt_new
                try:
                    line = input(prompt)
                except EOFError:
                    self.__write("\n")
                    break
                await self.__run_command(line)
            except KeyboardInterrupt:
                self.__resetbuffer()
                break
            except CommandNotFoundException as ex:
                self.__resetbuffer()
                self.__write(str(ex))
        if exitmsg is not None and exitmsg != '':
            self.__write('%s\n' % exitmsg)
