"""
《自私的基因》—— 重复囚徒困境锦标赛
基于 Axelrod 经典计算机实验的 Flask Web 交互版
"""

import random
from enum import Enum
from dataclasses import dataclass, field
from typing import Callable
import threading
import time

from flask import Flask, render_template
from flask_socketio import SocketIO, emit

# =============================================================================
# 博弈核心引擎
# =============================================================================


class Move(Enum):
    COOPERATE = 'C'
    DEFECT = 'D'

    def __str__(self):
        return self.value


class Payoff:
    """标准收益矩阵: T > R > P > S, T+S < 2R"""
    R = 3
    S = 0
    T = 5
    P = 1


def payoff(my_move: Move, opp_move: Move) -> tuple[int, int]:
    if my_move == Move.COOPERATE:
        if opp_move == Move.COOPERATE:
            return Payoff.R, Payoff.R
        return Payoff.S, Payoff.T
    else:
        if opp_move == Move.COOPERATE:
            return Payoff.T, Payoff.S
        return Payoff.P, Payoff.P


@dataclass
class MatchResult:
    p1_name: str
    p2_name: str
    score1: int
    score2: int
    coop1: int
    coop2: int
    total_rounds: int
    history: list = field(default_factory=list)

    @property
    def coop_rate1(self) -> float:
        return self.coop1 / self.total_rounds if self.total_rounds else 0

    @property
    def coop_rate2(self) -> float:
        return self.coop2 / self.total_rounds if self.total_rounds else 0


# =============================================================================
# 策略基类
# =============================================================================


class Strategy:
    name: str = "Unnamed"
    author: str = ""

    def reset(self):
        pass

    def move(self, my_history: list[Move], opp_history: list[Move]) -> Move:
        raise NotImplementedError


# =============================================================================
# 经典策略
# =============================================================================


class AlwaysCooperate(Strategy):
    name = "Always Cooperate"

    def move(self, my_history, opp_history):
        return Move.COOPERATE


class AlwaysDefect(Strategy):
    name = "Always Defect"

    def move(self, my_history, opp_history):
        return Move.DEFECT


class TitForTat(Strategy):
    name = "Tit for Tat"

    def move(self, my_history, opp_history):
        if not opp_history:
            return Move.COOPERATE
        return opp_history[-1]


class TitForTwoTats(Strategy):
    name = "Tit for Two Tats"

    def move(self, my_history, opp_history):
        if len(opp_history) < 2:
            return Move.COOPERATE
        if opp_history[-1] == Move.DEFECT and opp_history[-2] == Move.DEFECT:
            return Move.DEFECT
        return Move.COOPERATE


class Friedman(Strategy):
    name = "Friedman"

    def __init__(self):
        self.triggered = False

    def reset(self):
        self.triggered = False

    def move(self, my_history, opp_history):
        if not opp_history:
            return Move.COOPERATE
        if opp_history[-1] == Move.DEFECT:
            self.triggered = True
        return Move.DEFECT if self.triggered else Move.COOPERATE


class Joss(Strategy):
    name = "Joss"

    def __init__(self, defect_prob=0.1):
        self.defect_prob = defect_prob

    def move(self, my_history, opp_history):
        if not opp_history:
            return Move.COOPERATE
        if opp_history[-1] == Move.COOPERATE:
            return Move.DEFECT if random.random() < self.defect_prob else Move.COOPERATE
        return Move.DEFECT


class GenerousTitForTat(Strategy):
    name = "Generous TFT"

    def __init__(self, forgive_prob=0.1):
        self.forgive_prob = forgive_prob

    def move(self, my_history, opp_history):
        if not opp_history:
            return Move.COOPERATE
        if opp_history[-1] == Move.DEFECT:
            return Move.COOPERATE if random.random() < self.forgive_prob else Move.DEFECT
        return Move.COOPERATE


class RandomStrategy(Strategy):
    name = "Random"

    def __init__(self, coop_prob=0.5):
        self.coop_prob = coop_prob

    def move(self, my_history, opp_history):
        return Move.COOPERATE if random.random() < self.coop_prob else Move.DEFECT


class SuspiciousTitForTat(Strategy):
    name = "Suspicious TFT"

    def move(self, my_history, opp_history):
        if not opp_history:
            return Move.DEFECT
        return opp_history[-1]


# ID -> (Class, DisplayName) 映射
CLASSIC_STRATEGIES = {
    "AlwaysCooperate": (AlwaysCooperate, "🤝 Always Cooperate"),
    "AlwaysDefect": (AlwaysDefect, "🗡️ Always Defect"),
    "TitForTat": (TitForTat, "🔄 Tit for Tat"),
    "TitForTwoTats": (TitForTwoTats, "😊 Tit for Two Tats"),
    "Friedman": (Friedman, "❄️ Friedman"),
    "Joss": (Joss, "🦊 Joss"),
    "GenerousTFT": (GenerousTitForTat, "💝 Generous TFT"),
    "Random": (RandomStrategy, "🎲 Random"),
    "SuspiciousTFT": (SuspiciousTitForTat, "🤨 Suspicious TFT"),
}


# =============================================================================
# 自定义策略
# =============================================================================


class CustomStrategy(Strategy):
    def __init__(self, name: str, code: str):
        self._name = name
        self._code = code
        self._func: Callable | None = None

    @property
    def name(self):
        return self._name

    def compile(self):
        namespace = {"Move": Move, "random": random}
        exec(self._code, namespace)
        if "move" not in namespace:
            raise ValueError("自定义策略必须定义 move 函数")
        self._func = namespace["move"]
        return self

    def reset(self):
        pass

    def move(self, my_history, opp_history):
        if self._func is None:
            return Move.COOPERATE
        return self._func(my_history, opp_history)


CUSTOM_TEMPLATE = '''def move(my_history, opp_history):
    """my_history / opp_history: list[Move]
    返回: Move.COOPERATE 或 Move.DEFECT
    可用: random 模块
    """
    if not opp_history:
        return Move.COOPERATE

    defects = sum(1 for m in opp_history if m == Move.DEFECT)
    if defects > len(opp_history) * 0.3:
        return Move.DEFECT

    return opp_history[-1]
'''


# =============================================================================
# 比赛引擎
# =============================================================================


def run_match(s1: Strategy, s2: Strategy, rounds: int = 200,
              noise: float = 0.0) -> MatchResult:
    s1.reset()
    s2.reset()

    h1, h2 = [], []
    c1, c2 = 0, 0
    moves_log = []

    for _ in range(rounds):
        m1 = s1.move(h1, h2)
        m2 = s2.move(h1, h2)

        if noise > 0:
            if random.random() < noise:
                m1 = Move.DEFECT if m1 == Move.COOPERATE else Move.COOPERATE
            if random.random() < noise:
                m2 = Move.DEFECT if m2 == Move.COOPERATE else Move.COOPERATE

        h1.append(m1)
        h2.append(m2)

        if m1 == Move.COOPERATE:
            c1 += 1
        if m2 == Move.COOPERATE:
            c2 += 1

        p1, p2 = payoff(m1, m2)
        moves_log.append((str(m1), str(m2), p1, p2))

    return MatchResult(
        p1_name=s1.name, p2_name=s2.name,
        score1=sum(p[2] for p in moves_log),
        score2=sum(p[3] for p in moves_log),
        coop1=c1, coop2=c2,
        total_rounds=rounds,
        history=moves_log,
    )


# =============================================================================
# 循环锦标赛
# =============================================================================


def run_tournament(strategies: list[Strategy], rounds: int,
                   noise: float, sio: SocketIO | None = None):
    try:
        _run_tournament_impl(strategies, rounds, noise, sio)
    except Exception as e:
        import traceback
        err = traceback.format_exc()
        print(f"Tournament ERROR: {err}")
        if sio:
            try:
                sio.emit('error', {'message': f'锦标赛异常: {e}'})
                sio.emit('tournament_done', {'ranking': []})
            except:
                pass


def _run_tournament_impl(strategies: list[Strategy], rounds: int,
                         noise: float, sio: SocketIO | None = None):
    n = len(strategies)
    total_matches = n * (n - 1) // 2

    scores = {s.name: 0 for s in strategies}
    coop_counts = {s.name: 0 for s in strategies}
    match_counts = {s.name: 0 for s in strategies}
    wins = {s.name: 0 for s in strategies}
    history_log = []

    if sio:
        sio.emit('phase', {'phase': 'tournament', 'total_matches': total_matches,
                           'total_strategies': n})
        time.sleep(0.2)

    match_idx = 0
    for i in range(n):
        for j in range(i + 1, n):
            s1, s2 = strategies[i], strategies[j]
            match_idx += 1

            if sio:
                sio.emit('match_start', {
                    'match_id': match_idx, 'total': total_matches,
                    'p1': s1.name, 'p2': s2.name,
                })

            result = run_match(s1, s2, rounds, noise)

            scores[s1.name] += result.score1
            scores[s2.name] += result.score2
            coop_counts[s1.name] += result.coop1
            coop_counts[s2.name] += result.coop2
            match_counts[s1.name] += 1
            match_counts[s2.name] += 1
            if result.score1 > result.score2:
                wins[s1.name] += 1
            elif result.score2 > result.score1:
                wins[s2.name] += 1

            history_log.append({
                'p1': s1.name, 'p2': s2.name,
                's1': result.score1, 's2': result.score2,
                'c1': result.coop1, 'c2': result.coop2,
            })

            ranking = build_ranking(scores, wins, match_counts, coop_counts, rounds)
            match_detail = {
                'p1': s1.name, 'p2': s2.name,
                'rounds': result.total_rounds,
                'p1_coop_rate': round(result.coop_rate1, 3),
                'p2_coop_rate': round(result.coop_rate2, 3),
                'history': result.history,
            }

            if sio:
                sio.emit('match_result', {
                    'match_id': match_idx, 'total': total_matches,
                    'p1': s1.name, 'p2': s2.name,
                    'score1': result.score1, 'score2': result.score2,
                    'coop1': round(result.coop_rate1, 3),
                    'coop2': round(result.coop_rate2, 3),
                    'winner': s1.name if result.score1 > result.score2
                              else (s2.name if result.score2 > result.score1 else '平局'),
                })
                sio.emit('leaderboard', {'ranking': ranking})
                sio.emit('match_detail', match_detail)
                time.sleep(0.05)

    final_ranking = build_ranking(scores, wins, match_counts, coop_counts, rounds)
    if sio:
        sio.emit('tournament_done', {'ranking': final_ranking})
        sio.emit('status', {'message': '✅ 锦标赛完成！'})
    return final_ranking, history_log


def build_ranking(scores, wins, match_counts, coop_counts, base_rounds):
    sorted_names = sorted(scores.keys(), key=lambda n: scores[n], reverse=True)
    ranking = []
    for rank, name in enumerate(sorted_names, 1):
        mc = match_counts[name]
        total_r = mc * base_rounds
        ranking.append({
            'rank': rank,
            'name': name,
            'score': scores[name],
            'avg': round(scores[name] / mc, 1) if mc else 0,
            'wins': wins[name],
            'matches': mc,
            'win_rate': round(wins[name] / mc, 3) if mc else 0,
            'coop_rate': round(coop_counts[name] / total_r, 3) if total_r else 0,
        })
    return ranking


# =============================================================================
# 生态模拟（种群演化）
# =============================================================================


def run_ecology(strategies: list, rounds: int, noise: float,
                generations: int, sio: SocketIO | None = None):
    try:
        _run_ecology_impl(strategies, rounds, noise, generations, sio)
    except Exception as e:
        import traceback
        err = traceback.format_exc()
        print(f"Ecology ERROR: {err}")
        if sio:
            try:
                sio.emit('error', {'message': f'生态模拟异常: {e}'})
                sio.emit('ecology_done', {'final': {}})
            except:
                pass


def _run_ecology_impl(strategies: list, rounds: int, noise: float,
                      generations: int, sio: SocketIO | None = None):
    n = len(strategies)
    pop = {s.__class__.__name__: 100 for s in strategies}
    # 保留显示名称
    name_map = {s.__class__.__name__: s.name for s in strategies}

    if sio:
        sio.emit('phase', {'phase': 'ecology', 'generations': generations})
        time.sleep(0.2)

    for gen in range(generations):
        total_alive = sum(pop.values())
        if total_alive < 2 or sum(1 for v in pop.values() if v > 0) < 2:
            break

        # 按当前种群比例构建选手池
        pool = []
        for sid in pop:
            if pop[sid] > 0:
                cls, _ = CLASSIC_STRATEGIES.get(sid, (None, None))
                if cls is None:
                    continue
                pool.extend([cls] * pop[sid])

        if len(pool) < 2:
            break

        random.shuffle(pool)
        scores_indiv = {sid: 0 for sid in pop}
        count_indiv = {sid: 0 for sid in pop}

        for k in range(0, len(pool) - 1, 2):
            s1_cls, s2_cls = pool[k], pool[k + 1]
            s1, s2 = s1_cls(), s2_cls()
            s1.name = name_map.get(s1.__class__.__name__, s1.name)
            s2.name = name_map.get(s2.__class__.__name__, s2.name)
            result = run_match(s1, s2, rounds, noise)
            sid1, sid2 = s1.__class__.__name__, s2.__class__.__name__
            scores_indiv[sid1] += result.score1
            scores_indiv[sid2] += result.score2
            count_indiv[sid1] += 1
            count_indiv[sid2] += 1

        fitness = {}
        for sid in pop:
            if count_indiv[sid] > 0:
                fitness[sid] = scores_indiv[sid] / count_indiv[sid]
            else:
                fitness[sid] = 0

        avg_f = sum(fitness.values()) / max(len([v for v in fitness.values() if v > 0]), 1)

        new_pop = {}
        for sid in pop:
            if avg_f > 0 and fitness[sid] > 0:
                ratio = fitness[sid] / avg_f
                new_pop[sid] = max(5, int(pop[sid] * ratio))
            else:
                new_pop[sid] = 0
        pop = new_pop

        snapshot = {
            'generation': gen + 1,
            'populations': {name_map.get(sid, sid): pop[sid] for sid in pop},
        }
        if sio:
            sio.emit('ecology_update', snapshot)
            time.sleep(0.05)

    final = {name_map.get(sid, sid): pop[sid] for sid in pop}
    if sio:
        sio.emit('ecology_done', {'final': final})


# =============================================================================
# Flask App & SocketIO
# =============================================================================

app = Flask(__name__)
app.config['SECRET_KEY'] = 'ipd-secret-key'
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins='*')


@app.route('/')
def index():
    return render_template('index.html')


@socketio.on('connect')
def on_connect():
    emit('status', {'message': '已连接到 IPD 锦标赛服务器'})


@socketio.on('start_tournament')
def handle_tournament(data):
    selected = data.get('strategies', [])
    custom_list = data.get('custom_strategies', [])
    rounds = int(data.get('rounds', 200))
    noise = float(data.get('noise', 0.0))

    strats = []
    for sid in selected:
        if sid in CLASSIC_STRATEGIES:
            cls, display = CLASSIC_STRATEGIES[sid]
            s = cls()
            s.name = f"{display}"
            strats.append(s)

    for cs in custom_list:
        try:
            name = cs.get('name', 'MyStrategy')
            code = cs.get('code', '')
            custom = CustomStrategy(name, code)
            custom.compile()
            strats.append(custom)
        except Exception as e:
            emit('error', {'message': f'自定义策略 "{name}" 编译失败: {e}'})
            return

    if len(strats) < 2:
        emit('error', {'message': '至少选择 2 个策略'})
        return

    emit('status', {'message': f'🏟️ 锦标赛开始！{len(strats)} 个策略参与'})
    threading.Thread(target=run_tournament, args=(strats, rounds, noise, socketio), daemon=True).start()


@socketio.on('start_ecology')
def handle_ecology(data):
    selected = data.get('strategies', [])
    rounds = int(data.get('rounds', 200))
    noise = float(data.get('noise', 0.0))
    generations = int(data.get('generations', 30))

    strats = []
    for sid in selected:
        if sid in CLASSIC_STRATEGIES:
            cls, display = CLASSIC_STRATEGIES[sid]
            s = cls()
            s.name = f"{display}"
            strats.append(s)

    if len(strats) < 2:
        emit('error', {'message': '生态模拟至少需要 2 个策略'})
        return

    emit('status', {'message': f'🌿 生态模拟开始！{len(strats)} 个物种，{generations} 代'})
    threading.Thread(target=run_ecology, args=(strats, rounds, noise, generations, socketio), daemon=True).start()


if __name__ == '__main__':
    print("=" * 54)
    print("  IPD Tournament Arena")
    print("  基于《自私的基因》的重复囚徒困境实验")
    print("=" * 54)
    print("  打开浏览器 -> http://127.0.0.1:5000")
    print("=" * 54)
    socketio.run(app, host='127.0.0.1', port=5000, debug=True, use_reloader=False)
