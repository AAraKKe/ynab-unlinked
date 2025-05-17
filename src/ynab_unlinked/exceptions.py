from pathlib import Path


class ParsingError(Exception):
    def __init__(self, input_file: Path, message: str):
        self.input_file = input_file
        self.message = message
        super().__init__(message)
