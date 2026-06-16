from dataclasses import dataclass
from .player_config import PlayerConfig
from .team_config import TeamConfig

@dataclass
class BattleConfig:
    """战斗总配置"""
    player_config: PlayerConfig         # 玩家全局配置
    ally_team: TeamConfig               # 己方队伍
    enemy_team_id: str                  # 敌方预设ID (从数据加载)
    max_turns: int = 5                  # 最大回合数
