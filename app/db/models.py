from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255))
    first_name: Mapped[str] = mapped_column(String(255), default="")
    last_name: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255), default="")
    bio: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[str] = mapped_column(Text, default="")
    name_base: Mapped[str] = mapped_column(String(255), default="")
    display_name_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    active_tag_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notify_game_result: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_achievements: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_rank_changes: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_challenges: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_turns: Mapped[bool] = mapped_column(Boolean, default=True)
    games_played: Mapped[int] = mapped_column(Integer, default=0)
    games_won: Mapped[int] = mapped_column(Integer, default=0)
    mafia_wins: Mapped[int] = mapped_column(Integer, default=0)
    citizen_wins: Mapped[int] = mapped_column(Integer, default=0)
    independent_wins: Mapped[int] = mapped_column(Integer, default=0)
    challenges: Mapped[int] = mapped_column(Integer, default=0)
    kills: Mapped[int] = mapped_column(Integer, default=0)
    saves: Mapped[int] = mapped_column(Integer, default=0)
    investigations: Mapped[int] = mapped_column(Integer, default=0)
    investigation_hits: Mapped[int] = mapped_column(Integer, default=0)
    correct_votes: Mapped[int] = mapped_column(Integer, default=0)
    challenges_accepted: Mapped[int] = mapped_column(Integer, default=0)
    faceoffs: Mapped[int] = mapped_column(Integer, default=0)
    faceoff_wins: Mapped[int] = mapped_column(Integer, default=0)
    kicks: Mapped[int] = mapped_column(Integer, default=0)
    games_survived: Mapped[int] = mapped_column(Integer, default=0)
    win_streak: Mapped[int] = mapped_column(Integer, default=0)
    best_win_streak: Mapped[int] = mapped_column(Integer, default=0)
    achievements_count: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    registered_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class Group(Base):
    __tablename__ = "groups"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    username: Mapped[str | None] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(32), default="supergroup")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    registered_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class GroupSettings(Base):
    __tablename__ = "group_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), unique=True)
    chat_lock: Mapped[bool] = mapped_column(Boolean, default=False)
    night_lock: Mapped[bool] = mapped_column(Boolean, default=False)
    turn_lock: Mapped[bool] = mapped_column(Boolean, default=False)
    custom_emoji: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class Scenario(Base):
    __tablename__ = "scenarios"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True)
    name_fa: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    min_players: Mapped[int] = mapped_column(Integer)
    max_players: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    challenge_mode: Mapped[str] = mapped_column(String(20), default="limited")
    challenge_limit: Mapped[int | None] = mapped_column(Integer, nullable=True, default=1)
    turn_seconds: Mapped[int] = mapped_column(Integer, default=120)
    challenge_seconds: Mapped[int] = mapped_column(Integer, default=60)
    vote_defense_threshold: Mapped[int] = mapped_column(Integer, default=2)
    # JSON snapshot of scenario-specific voting rules. Legacy threshold remains as fallback.
    voting_rules: Mapped[str] = mapped_column(Text, default="{}")
    extra_challenge_seconds: Mapped[int] = mapped_column(Integer, default=60)
    training_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    telegram_training_url: Mapped[str | None] = mapped_column(Text, nullable=True)

class ScenarioRole(Base):
    __tablename__ = "scenario_roles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"))
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"))
    count: Mapped[int] = mapped_column(Integer, default=1)
    position: Mapped[int] = mapped_column(Integer, default=0)

class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True)
    name_fa: Mapped[str] = mapped_column(String(255))
    team: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text, default="")

class Game(Base):
    __tablename__ = "games"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"))
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenarios.id"))
    host_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    # Game creation settings persisted by migration 0005.
    auto_play: Mapped[bool] = mapped_column(Boolean, default=False)
    turn_color: Mapped[str] = mapped_column(String(50), default="پیش‌فرض")
    challenge_color: Mapped[str] = mapped_column(String(50), default="پیش‌فرض")
    reserve_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    challenge_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    challenge_mode: Mapped[str] = mapped_column(String(20), default="limited")
    challenge_limit: Mapped[int | None] = mapped_column(Integer, nullable=True, default=1)
    turn_seconds: Mapped[int] = mapped_column(Integer, default=120)
    challenge_seconds: Mapped[int] = mapped_column(Integer, default=60)
    extra_challenge_seconds: Mapped[int] = mapped_column(Integer, default=60)
    next_host_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    next_player_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    next_auto_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_silence_warnings: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_kick_warnings: Mapped[bool] = mapped_column(Boolean, default=False)
    turn_color_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    voting_pre_delay_seconds: Mapped[int] = mapped_column(Integer, default=10)
    vote_seconds: Mapped[int] = mapped_column(Integer, default=10)
    voting_mode: Mapped[str] = mapped_column(String(20), default="manual")
    vote2_selection_mode: Mapped[str] = mapped_column(String(20), default="manual")
    emoji_settings: Mapped[str] = mapped_column(Text, default='{"death": true, "kick": true, "slaughter": true, "challenge": true, "silence": true, "extra_turn": true, "warning": true}')
    status: Mapped[str] = mapped_column(String(30), default="waiting")
    phase: Mapped[str] = mapped_column(String(30), default="lobby")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class GamePlayer(Base):
    __tablename__ = "game_players"
    __table_args__ = (
        UniqueConstraint("game_id", "user_id", name="uq_game_player_user"),
        UniqueConstraint("game_id", "seat", name="uq_game_player_seat"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    seat: Mapped[int] = mapped_column(Integer)
    is_reserved: Mapped[bool] = mapped_column(Boolean, default=False)
    reserve_position: Mapped[int | None] = mapped_column(Integer)
    role_id: Mapped[int | None] = mapped_column(ForeignKey("roles.id"))
    alive: Mapped[bool] = mapped_column(Boolean, default=True)
    exit_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    silence_until_round: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extra_turn_round: Mapped[int | None] = mapped_column(Integer, nullable=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class GameEvent(Base):
    __tablename__ = "game_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"))
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    event_type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class Vote(Base):
    __tablename__ = "votes"
    __table_args__ = (
        UniqueConstraint("game_id", "voter_user_id", "target_user_id", "round_no", "phase", name="uq_vote_per_target"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"))
    voter_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    target_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    round_no: Mapped[int] = mapped_column(Integer, default=1)
    phase: Mapped[str] = mapped_column(String(20), default="vote1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Achievement(Base):
    __tablename__ = "achievements"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name_fa: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    icon: Mapped[str] = mapped_column(String(20), default="🏅")
    points: Mapped[int] = mapped_column(Integer, default=0)
    tag_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tag_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tag_emoji: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class UserAchievement(Base):
    __tablename__ = "user_achievements"
    __table_args__ = (UniqueConstraint("user_id", "achievement_id", name="uq_user_achievement"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    achievement_id: Mapped[int] = mapped_column(ForeignKey("achievements.id", ondelete="CASCADE"))
    earned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserRoleStat(Base):
    __tablename__ = "user_role_stats"
    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uq_user_role_stat"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"))
    games: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    kills: Mapped[int] = mapped_column(Integer, default=0)
    saves: Mapped[int] = mapped_column(Integer, default=0)
    investigations: Mapped[int] = mapped_column(Integer, default=0)
    investigation_hits: Mapped[int] = mapped_column(Integer, default=0)
