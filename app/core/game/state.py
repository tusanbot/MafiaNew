from enum import StrEnum

class GamePhase(StrEnum):
    LOBBY = "lobby"
    SETUP = "setup"
    NIGHT = "night"
    DAY = "day"
    VOTING = "voting"
    RESULT = "result"
    FINISHED = "finished"

class GameStatus(StrEnum):
    WAITING = "waiting"
    RUNNING = "running"
    FINISHED = "finished"
    CANCELLED = "cancelled"
