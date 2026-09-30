from dataclasses import dataclass, field

@dataclass
class Lobby:
    group_id:int
    host_id:int
    scenario_id:str
    players:list[int]=field(default_factory=list)
    max_players:int=0
    started:bool=False

    def join(self, user_id:int)->bool:
        if self.started or user_id in self.players or (self.max_players and len(self.players)>=self.max_players): return False
        self.players.append(user_id); return True
    def leave(self,user_id:int)->bool:
        if user_id not in self.players or self.started: return False
        self.players.remove(user_id); return True
    def can_start(self,min_players:int)->bool:
        return not self.started and len(self.players)>=min_players
