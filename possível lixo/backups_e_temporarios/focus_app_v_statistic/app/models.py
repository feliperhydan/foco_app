"""
Modelo de dados do FOCUS.

Este módulo implementa a Camada 1 (Registro) e as entidades de
Camada 2 (Progresso) descritas no Manual de Implementação.

Decisões de design que valem para todo o arquivo
--------------------------------------------------
1. CICLO ≠ MINUTO (regra absoluta do manual, seção 2)
   `FocusCycle.focus_duration_minutes` e `RestCycle.duration_minutes`
   são SNAPSHOTS gravados no momento em que o ciclo é criado — nunca
   recalculados a partir da Configuration vigente no momento da
   consulta. Estatísticas devem sempre somar esses campos, nunca
   `total_de_ciclos * configuração_atual` (seção 2 e 41).

2. CONFIGURAÇÃO COM VIGÊNCIA (seção 6)
   `Configuration` nunca é editada depois de criada (exceto para
   fechar `valid_to` quando uma nova a substitui). Uma alteração de
   parâmetro sempre cria uma linha nova. Isto vale tanto para os
   parâmetros do pomodoro quanto para as metas (mínima/ideal/semanal)
   e para hidratação/tema — o briefing visual trata tudo isso como um
   único "pacote de configuração vigente" (ex.: "Configuração A —
   01/08→10/08 — Foco 35min, Meta ideal 8"), então modelamos como uma
   única entidade versionada em vez de várias tabelas de vigência
   paralelas. Ver `Configuration` abaixo para o racional completo.

3. DERIVAÇÃO, NÃO DUPLICAÇÃO (seção 41)
   Nada neste módulo armazena totais agregados que pudessem divergir
   dos registros reais. Totais (ciclos, minutos, dias ativos) são
   sempre calculados por query a partir de `FocusCycle` — ver
   `app/services/` (camada seguinte) para as funções de agregação.

4. Este módulo é só o modelo de dados + persistência (Camada 1 do
   manual, seção 43). O motor de conclusão de ciclo (seção 17, 42),
   a lógica de extraordinário, recompensas etc. entram na Camada 5
   (services), ainda não implementada aqui — os campos já existem
   para suportá-la, mas nenhuma regra de negócio roda neste arquivo.
"""
from datetime import datetime, date as date_

from app.extensions import db
from app.services.time_utils import utcnow_naive


# ---------------------------------------------------------------------------
# Mixins
# ---------------------------------------------------------------------------

class TimestampMixin:
    """created_at / updated_at padrão para auditoria básica."""
    created_at = db.Column(db.DateTime, default=utcnow_naive, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=utcnow_naive, onupdate=utcnow_naive, nullable=False
    )


# ---------------------------------------------------------------------------
# CAMADA 1 — REGISTRO
# ---------------------------------------------------------------------------

class DebugState(db.Model, TimestampMixin):
    """
    Estado global de debug.

    Hoje ele guarda só o deslocamento do relógio do aplicativo, usado
    para avançar dias sem mexer no relógio real do sistema.
    """
    __tablename__ = "debug_state"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(40), nullable=False, unique=True, default="clock")
    clock_offset_days = db.Column(db.Integer, nullable=False, default=0)
    test_data_start_date = db.Column(db.Date, nullable=True)
    test_data_end_date = db.Column(db.Date, nullable=True)
    test_data_generated_at = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f"<DebugState {self.name} offset_days={self.clock_offset_days}>"


class Configuration(db.Model, TimestampMixin):
    """
    Pacote de configuração vigente (manual, seção 6, 7, 33).

    Cada linha representa o conjunto de parâmetros válidos durante um
    período (`valid_from` → `valid_to`). Quando o usuário muda
    qualquer parâmetro:
        1. a configuração atual tem `valid_to` preenchido com "agora";
        2. uma nova linha é criada com `valid_from = agora` e
           `valid_to = None` (None = vigente).
    Nunca se edita `valid_from`/`valid_to` de uma linha já fechada, e
    nunca se editam os parâmetros de uma linha depois de criada — ela
    é o snapshot histórico exato daquele período (seção 7: "Snapshot
    de contexto").

    Exatamente uma linha por usuário deve ter `valid_to IS NULL` em
    um dado momento — isso é responsabilidade da camada de serviço
    (não é reforçado aqui via constraint para manter o SQLite simples
    nesta primeira etapa).
    """
    __tablename__ = "configurations"

    id = db.Column(db.Integer, primary_key=True)

    valid_from = db.Column(db.DateTime, nullable=False, default=utcnow_naive)
    valid_to = db.Column(db.DateTime, nullable=True)  # None = vigente

    # --- parâmetros do pomodoro ---
    focus_minutes = db.Column(db.Integer, nullable=False, default=35)
    short_break_minutes = db.Column(db.Integer, nullable=False, default=5)
    long_break_minutes = db.Column(db.Integer, nullable=False, default=20)
    cycles_per_session = db.Column(db.Integer, nullable=False, default=4)

    # --- metas estruturais (snapshot; cada Progress também guarda a
    #     própria meta no momento em que a instância foi criada — ver
    #     nota em DailyMinimumProgress) ---
    daily_minimum_goal = db.Column(db.Integer, nullable=False, default=6)
    daily_ideal_goal = db.Column(db.Integer, nullable=False, default=8)
    weekly_goal = db.Column(db.Integer, nullable=False, default=36)

    # --- hidratação ---
    water_bottle_ml = db.Column(db.Integer, nullable=False, default=750)
    water_goal_ml = db.Column(db.Integer, nullable=False, default=3500)

    # --- aparência (não afeta dados, mas tem vigência por simplicidade) ---
    theme = db.Column(db.String(10), nullable=False, default="dark")  # 'light' | 'dark' | 'auto'
    primary_color = db.Column(db.String(7), nullable=False, default="#1F5C45")
    debug_tools_enabled = db.Column(db.Boolean, nullable=False, default=False)

    # relacionamentos reversos (somente leitura / navegação)
    focus_cycles = db.relationship("FocusCycle", back_populates="configuration")
    rest_cycles = db.relationship("RestCycle", back_populates="configuration")

    @property
    def is_current(self) -> bool:
        return self.valid_to is None

    def __repr__(self):
        return f"<Configuration id={self.id} focus={self.focus_minutes}min vigente={self.is_current}>"


class Session(db.Model, TimestampMixin):
    """
    Sessão de trabalho (manual, seção 3.1).

    Um dia pode ter várias sessões. A sessão é criada (ou reaberta)
    quando o primeiro ciclo do agrupamento é iniciado.
    """
    __tablename__ = "sessions"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, default=date_.today, index=True)
    started_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)
    ended_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="active")  # active | ended

    focus_cycles = db.relationship(
        "FocusCycle", back_populates="session", order_by="FocusCycle.started_at"
    )
    rest_cycles = db.relationship(
        "RestCycle", back_populates="session", order_by="RestCycle.started_at"
    )

    def __repr__(self):
        return f"<Session id={self.id} date={self.date} status={self.status}>"


class FocusCycle(db.Model, TimestampMixin):
    """
    Ciclo de foco (manual, seção 4) — a entidade operacional central.

    `focus_duration_minutes` é copiado da Configuration vigente no
    instante de `started_at` e NUNCA é recalculado depois — mesmo que
    a Configuration mude ou seja substituída. Isso é o que garante a
    regra "ciclo #100 continua representando 35 minutos para sempre"
    (seção 2).

    Só ciclos com status='completed' entram em qualquer contagem de
    progresso, estatística ou calendário (seção 4, regra fundamental:
    "um ciclo só entra no progresso quando é concluído").
    """
    __tablename__ = "focus_cycles"

    id = db.Column(db.Integer, primary_key=True)

    session_id = db.Column(db.Integer, db.ForeignKey("sessions.id"), nullable=False, index=True)
    configuration_id = db.Column(
        db.Integer, db.ForeignKey("configurations.id"), nullable=False
    )

    started_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)
    completed_at = db.Column(db.DateTime, nullable=True)

    # snapshot imutável — nunca ler configuration.focus_minutes para
    # reconstruir isso depois do fato.
    focus_duration_minutes = db.Column(db.Integer, nullable=False)

    title = db.Column(db.String(280), nullable=True)  # "O que você fez?" — opcional

    status = db.Column(db.String(20), nullable=False, default="started", index=True)
    # started | completed | abandoned

    session = db.relationship("Session", back_populates="focus_cycles")
    configuration = db.relationship("Configuration", back_populates="focus_cycles")

    __table_args__ = (
        db.Index("ix_focus_cycles_status_completed_at", "status", "completed_at"),
    )

    def __repr__(self):
        return (
            f"<FocusCycle id={self.id} status={self.status} "
            f"{self.focus_duration_minutes}min>"
        )


class RestCycle(db.Model, TimestampMixin):
    """
    Ciclo de descanso (manual, seção 5) — mesma lógica de snapshot do
    FocusCycle. `duration_minutes` é copiado da Configuration vigente
    no início do descanso.
    """
    __tablename__ = "rest_cycles"

    id = db.Column(db.Integer, primary_key=True)

    session_id = db.Column(db.Integer, db.ForeignKey("sessions.id"), nullable=False, index=True)
    configuration_id = db.Column(
        db.Integer, db.ForeignKey("configurations.id"), nullable=False
    )

    kind = db.Column(db.String(10), nullable=False)  # 'short' | 'long'
    duration_minutes = db.Column(db.Integer, nullable=False)

    started_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)
    ended_at = db.Column(db.DateTime, nullable=True)

    status = db.Column(db.String(20), nullable=False, default="started")
    # started | completed | abandoned

    session = db.relationship("Session", back_populates="rest_cycles")
    configuration = db.relationship("Configuration", back_populates="rest_cycles")

    def __repr__(self):
        return f"<RestCycle id={self.id} kind={self.kind} {self.duration_minutes}min>"


# ---------------------------------------------------------------------------
# CAMADA 2 — PROGRESSO
# ---------------------------------------------------------------------------

class DailyMinimumProgress(db.Model, TimestampMixin):
    """
    Progresso Diário Mínimo (manual, seção 9).

    Uma linha por data. `goal` é snapshotado da Configuration vigente
    no momento em que a instância do dia é criada — se a meta mudar
    no meio do dia, o dia já em curso mantém a meta com que começou
    (comportamento a confirmar na camada de serviço; o campo já
    suporta isso).
    """
    __tablename__ = "daily_minimum_progress"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True, index=True)

    goal = db.Column(db.Integer, nullable=False)
    current_count = db.Column(db.Integer, nullable=False, default=0)

    configuration_id = db.Column(db.Integer, db.ForeignKey("configurations.id"), nullable=False)

    status = db.Column(db.String(20), nullable=False, default="pending")  # pending | completed
    completed_at = db.Column(db.DateTime, nullable=True)

    configuration = db.relationship("Configuration")

    def __repr__(self):
        return f"<DailyMinimumProgress {self.date} {self.current_count}/{self.goal}>"


class DailyIdealProgress(db.Model, TimestampMixin):
    """Progresso Diário Ideal (manual, seção 10). Mesma estrutura do mínimo."""
    __tablename__ = "daily_ideal_progress"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True, index=True)

    goal = db.Column(db.Integer, nullable=False)
    current_count = db.Column(db.Integer, nullable=False, default=0)

    configuration_id = db.Column(db.Integer, db.ForeignKey("configurations.id"), nullable=False)

    status = db.Column(db.String(20), nullable=False, default="pending")  # pending | completed
    completed_at = db.Column(db.DateTime, nullable=True)

    extraordinary = db.relationship(
        "ExtraordinaryProgress", back_populates="daily_ideal", uselist=False
    )
    configuration = db.relationship("Configuration")

    def __repr__(self):
        return f"<DailyIdealProgress {self.date} {self.current_count}/{self.goal}>"


class ExtraordinaryProgress(db.Model, TimestampMixin):
    """
    Progresso Extraordinário (manual, seção 11).

    Só passa a existir (linha criada) no instante em que o
    DailyIdealProgress correspondente completa — nunca antes. É por
    isso que a Home "esconde" a barra: a ausência de linha nesta
    tabela para o dia É o estado "ainda não desbloqueado". Não existe
    um campo booleano "unlocked" — a existência da linha é o sinal.
    """
    __tablename__ = "extraordinary_progress"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True, index=True)

    daily_ideal_id = db.Column(
        db.Integer, db.ForeignKey("daily_ideal_progress.id"), nullable=False
    )
    configuration_id = db.Column(db.Integer, db.ForeignKey("configurations.id"), nullable=False)

    extra_cycles = db.Column(db.Integer, nullable=False, default=0)
    extra_minutes = db.Column(db.Integer, nullable=False, default=0)

    unlocked_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)

    daily_ideal = db.relationship("DailyIdealProgress", back_populates="extraordinary")
    configuration = db.relationship("Configuration")

    def __repr__(self):
        return f"<ExtraordinaryProgress {self.date} +{self.extra_cycles}>"


class WeeklyProgress(db.Model, TimestampMixin):
    """Progresso Semanal (manual, seção 12). Uma linha por semana (week_start/week_end)."""
    __tablename__ = "weekly_progress"

    id = db.Column(db.Integer, primary_key=True)
    week_start = db.Column(db.Date, nullable=False, index=True)
    week_end = db.Column(db.Date, nullable=False)

    goal = db.Column(db.Integer, nullable=False)
    current_count = db.Column(db.Integer, nullable=False, default=0)

    configuration_id = db.Column(db.Integer, db.ForeignKey("configurations.id"), nullable=False)

    status = db.Column(db.String(20), nullable=False, default="pending")  # pending | completed
    completed_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint("week_start", "week_end", name="uq_weekly_progress_period"),
    )

    configuration = db.relationship("Configuration")

    def __repr__(self):
        return f"<WeeklyProgress {self.week_start}→{self.week_end} {self.current_count}/{self.goal}>"


class AbsoluteProgress(db.Model, TimestampMixin):
    """
    Progresso Absoluto / Atemporal (manual, seção 13).

    Não reseta — permanece ativo até `current_count >= goal_cycles`,
    quando `status` vira 'completed' e o progresso para de acumular
    (seção 13: "não deve continuar acumulando depois de concluído").
    """
    __tablename__ = "absolute_progress"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)

    goal_cycles = db.Column(db.Integer, nullable=False)
    current_count = db.Column(db.Integer, nullable=False, default=0)

    started_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)
    completed_at = db.Column(db.DateTime, nullable=True)

    status = db.Column(db.String(20), nullable=False, default="active")  # active | completed

    # se este objetivo nasceu de um item da wishlist, guardamos o vínculo
    wishlist_item_id = db.Column(
        db.Integer, db.ForeignKey("wishlist_items.id"), nullable=True
    )

    def __repr__(self):
        return f"<AbsoluteProgress {self.title} {self.current_count}/{self.goal_cycles}>"


class AbsoluteProgressDailyLog(db.Model, TimestampMixin):
    """
    Log diário de progresso de um objetivo absoluto.

    Registra start_count e end_count para evitar dependência de dados vivos
    durante a consolidação e reconstrução histórica.
    """
    __tablename__ = "absolute_progress_daily_logs"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, index=True)
    absolute_progress_id = db.Column(
        db.Integer,
        db.ForeignKey("absolute_progress.id"),
        nullable=False
    )

    start_count = db.Column(db.Integer, nullable=False)
    end_count = db.Column(db.Integer, nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            "date",
            "absolute_progress_id",
            name="uq_abs_daily_log"
        ),
    )

    absolute_progress = db.relationship("AbsoluteProgress")

    def __repr__(self):
        return f"<AbsoluteProgressDailyLog progress_id={self.absolute_progress_id} date={self.date} {self.start_count}→{self.end_count}>"


class WishlistItem(db.Model, TimestampMixin):
    """
    Item da Wishlist (manual, seção 14).

    NÃO é progresso — é só uma lista de candidatos. Ao ser ativado,
    gera um `AbsoluteProgress` novo (o item em si só muda de status
    para 'activated' e passa a referenciar esse progresso).
    """
    __tablename__ = "wishlist_items"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    suggested_goal = db.Column(db.Integer, nullable=False)
    order = db.Column(db.Integer, nullable=False, default=0)

    status = db.Column(db.String(20), nullable=False, default="wishlist")  # wishlist | activated

    activated_progress = db.relationship("AbsoluteProgress", backref="wishlist_source", uselist=False)

    def __repr__(self):
        return f"<WishlistItem {self.title} ({self.status})>"


# ---------------------------------------------------------------------------
# TO-DO LATERAL
# ---------------------------------------------------------------------------

class TodoItem(db.Model, TimestampMixin):
    """
    Item de to-do pessoal: lista lateral e discreta, sem relacao com o
    motor de ciclos/progresso do FOCUS. Ordenacao por `order` (ordem de
    criacao); `done` e um booleano simples, sem historico de conclusao.
    """
    __tablename__ = "todo_items"

    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.String(140), nullable=False, default="")
    done = db.Column(db.Boolean, nullable=False, default=False)
    order = db.Column(db.Integer, nullable=False, default=0, index=True)

    def __repr__(self):
        return f"<TodoItem id={self.id} done={self.done} '{self.text[:20]}'>"


class TodoListState(db.Model, TimestampMixin):
    """
    Estado diario da to-do list. Os itens e seus textos sao persistentes;
    esta linha registra a data a que os checks atuais pertencem.
    """
    __tablename__ = "todo_list_state"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(40), nullable=False, unique=True, default="default")
    last_completed_date = db.Column(db.Date, nullable=False, default=date_.today)

    def __repr__(self):
        return f"<TodoListState {self.name} last_completed_date={self.last_completed_date}>"


# ---------------------------------------------------------------------------
# DAILY HISTORICO
# ---------------------------------------------------------------------------

class Daily(db.Model, TimestampMixin):
    """
    Registro historico fundamental das estatisticas.

    Daily guarda dados brutos e contexto em snapshots autocontidos. Week
    e Month devem ser construidos posteriormente como agregacoes destes
    registros, sem reescrever o passado.
    """
    __tablename__ = "daily"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True, index=True)
    session_started = db.Column(db.Boolean, nullable=False, default=False)

    cycle_contexts = db.Column(db.JSON, nullable=False, default=list)
    # Cronologia individual de cada FocusCycle concluído (completed_at + title).
    # Congelado na consolidação — nunca reler de FocusCycle após consolidated_at.
    focus_timeline = db.Column(db.JSON, nullable=True, default=list)
    # Snapshot da sessao estatistica diaria (started, started_at, ended_at).
    # Nao representa sessoes Pomodoro nem contagem de Session operacional.
    # Congelado na consolidacao — nunca reler de Session apos consolidated_at.
    session = db.Column(db.JSON, nullable=True, default=dict)
    water = db.Column(db.JSON, nullable=False, default=dict)
    todo = db.Column(db.JSON, nullable=False, default=dict)
    rewards = db.Column(db.JSON, nullable=False, default=dict)
    consolidated_at = db.Column(db.DateTime, nullable=True)

    def as_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "session_started": self.session_started,
            "session": self.session,
            "cycle_contexts": self.cycle_contexts or [],
            "focus_timeline": self.focus_timeline or [],
            "water": self.water or {"contexts": []},
            "todo": self.todo or {"items_total": 0, "items_completed": 0},
            "rewards": self.rewards or {},
            "consolidated_at": self.consolidated_at.isoformat() if self.consolidated_at else None,
        }

    def __repr__(self):
        return f"<Daily {self.date} session_started={self.session_started}>"


class Week(db.Model, TimestampMixin):
    """
    Agregado historico semanal construido exclusivamente a partir de Daily.

    A semana e uma unidade calendario estavel (segunda a domingo). Week
    guarda agregados brutos e vinculos para os Daily usados; o detalhe
    diario continua pertencendo ao Daily.
    """
    __tablename__ = "weeks"

    id = db.Column(db.Integer, primary_key=True)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="active")
    consolidated_at = db.Column(db.DateTime, nullable=True)

    days = db.Column(db.JSON, nullable=False, default=list)
    totals = db.Column(db.JSON, nullable=False, default=dict)
    contexts = db.Column(db.JSON, nullable=False, default=list)
    titles = db.Column(db.JSON, nullable=False, default=list)
    water = db.Column(db.JSON, nullable=False, default=dict)
    todo = db.Column(db.JSON, nullable=False, default=dict)
    rewards = db.Column(db.JSON, nullable=False, default=dict)
    absolute = db.Column(db.JSON, nullable=False, default=dict)

    daily_links = db.relationship(
        "WeekDaily",
        back_populates="week",
        cascade="all, delete-orphan",
        order_by="WeekDaily.date",
    )

    __table_args__ = (
        db.UniqueConstraint("start_date", "end_date", name="uq_weeks_period"),
    )

    def as_dict(self) -> dict:
        return {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "status": self.status,
            "consolidated_at": self.consolidated_at.isoformat() if self.consolidated_at else None,
            "days": self.days or [],
            "totals": self.totals or {},
            "contexts": self.contexts or [],
            "titles": self.titles or [],
            "water": self.water or {},
            "todo": self.todo or {},
            "rewards": self.rewards or {},
            "absolute": self.absolute or {},
        }

    def __repr__(self):
        return f"<Week {self.start_date}->{self.end_date} status={self.status}>"


class WeekDaily(db.Model, TimestampMixin):
    """
    Vinculo explicito entre uma Week agregada e os Daily usados nela.
    """
    __tablename__ = "week_daily"

    id = db.Column(db.Integer, primary_key=True)
    week_id = db.Column(db.Integer, db.ForeignKey("weeks.id"), nullable=False, index=True)
    daily_id = db.Column(db.Integer, db.ForeignKey("daily.id"), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)

    week = db.relationship("Week", back_populates="daily_links")
    daily = db.relationship("Daily")

    __table_args__ = (
        db.UniqueConstraint("week_id", "daily_id", name="uq_week_daily_link"),
        db.UniqueConstraint("week_id", "date", name="uq_week_daily_date"),
    )

    def __repr__(self):
        return f"<WeekDaily week_id={self.week_id} date={self.date}>"


class Month(db.Model, TimestampMixin):
    """
    Agregado historico mensal construido exclusivamente a partir de Daily.

    O Month guarda agregados brutos e vinculos para os Daily usados; o detalhe
    diario continua pertencendo ao Daily.
    """
    __tablename__ = "months"

    id = db.Column(db.Integer, primary_key=True)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="active")
    consolidated_at = db.Column(db.DateTime, nullable=True)

    days = db.Column(db.JSON, nullable=False, default=list)
    totals = db.Column(db.JSON, nullable=False, default=dict)
    contexts = db.Column(db.JSON, nullable=False, default=list)
    titles = db.Column(db.JSON, nullable=False, default=list)
    water = db.Column(db.JSON, nullable=False, default=dict)
    todo = db.Column(db.JSON, nullable=False, default=dict)
    rewards = db.Column(db.JSON, nullable=False, default=dict)
    absolute = db.Column(db.JSON, nullable=False, default=dict)

    daily_links = db.relationship(
        "MonthDaily",
        back_populates="month",
        cascade="all, delete-orphan",
        order_by="MonthDaily.date",
    )

    __table_args__ = (
        db.UniqueConstraint("start_date", "end_date", name="uq_months_period"),
    )

    def as_dict(self) -> dict:
        return {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "status": self.status,
            "consolidated_at": self.consolidated_at.isoformat() if self.consolidated_at else None,
            "days": self.days or [],
            "totals": self.totals or {},
            "contexts": self.contexts or [],
            "titles": self.titles or [],
            "water": self.water or {},
            "todo": self.todo or {},
            "rewards": self.rewards or {},
            "absolute": self.absolute or {},
        }

    def __repr__(self):
        return f"<Month {self.start_date}->{self.end_date} status={self.status}>"


class MonthDaily(db.Model, TimestampMixin):
    """
    Vinculo explicito entre um Month agregado e os Daily usados nele.
    """
    __tablename__ = "month_daily"

    id = db.Column(db.Integer, primary_key=True)
    month_id = db.Column(db.Integer, db.ForeignKey("months.id"), nullable=False, index=True)
    daily_id = db.Column(db.Integer, db.ForeignKey("daily.id"), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)

    month = db.relationship("Month", back_populates="daily_links")
    daily = db.relationship("Daily")

    __table_args__ = (
        db.UniqueConstraint("month_id", "daily_id", name="uq_month_daily_link"),
        db.UniqueConstraint("month_id", "date", name="uq_month_daily_date"),
    )

    def __repr__(self):
        return f"<MonthDaily month_id={self.month_id} date={self.date}>"


# ---------------------------------------------------------------------------
# RECOMPENSAS
# ---------------------------------------------------------------------------

class Reward(db.Model, TimestampMixin):
    """
    Definição de recompensa (manual, seção 15).

    Desacoplada da entidade de progresso: o título é variável, a
    entidade estrutural (`progress_type`) é fixa. `progress_type`
    identifica a QUAL tipo de progresso essa recompensa está ligada;
    `absolute_progress_id` só é usado quando `progress_type ==
    'absolute'`, para apontar para o objetivo absoluto específico.
    """
    __tablename__ = "rewards"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)

    progress_type = db.Column(db.String(20), nullable=False)
    # 'daily_minimum' | 'daily_ideal' | 'weekly' | 'absolute'

    absolute_progress_id = db.Column(
        db.Integer, db.ForeignKey("absolute_progress.id"), nullable=True
    )

    active = db.Column(db.Boolean, nullable=False, default=True)

    achievements = db.relationship(
        "RewardAchievement", back_populates="reward", order_by="RewardAchievement.achieved_date"
    )

    def __repr__(self):
        return f"<Reward {self.title} ({self.progress_type})>"


class RewardAchievement(db.Model, TimestampMixin):
    """
    Conquista de recompensa (manual, seção 16) — um registro histórico
    por vez que a recompensa foi atingida.

    `start_date`/`end_date` são usados para recompensas que
    representam um período (ex.: "Praia: 06/08 → 09/08"); para
    recompensas diárias, só `achieved_date` é preenchido.
    """
    __tablename__ = "reward_achievements"

    id = db.Column(db.Integer, primary_key=True)
    reward_id = db.Column(db.Integer, db.ForeignKey("rewards.id"), nullable=False, index=True)
    title_snapshot = db.Column(db.String(120), nullable=True)

    achieved_date = db.Column(db.Date, nullable=False, default=date_.today)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)

    reward = db.relationship("Reward", back_populates="achievements")

    def __repr__(self):
        return f"<RewardAchievement reward_id={self.reward_id} {self.achieved_date}>"


# ---------------------------------------------------------------------------
# HIDRATAÇÃO
# ---------------------------------------------------------------------------

class WaterLog(db.Model, TimestampMixin):
    """
    Registro manual de hidratação (manual, seção 28).

    `volume_ml` é um snapshot — copiado de `Configuration.water_bottle_ml`
    no instante do registro, pelo mesmo motivo dos ciclos: se o
    usuário trocar de garrafa, os registros antigos não podem mudar
    de tamanho retroativamente.
    """
    __tablename__ = "water_logs"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, default=date_.today, index=True)
    logged_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)

    volume_ml = db.Column(db.Integer, nullable=False)
    configuration_id = db.Column(db.Integer, db.ForeignKey("configurations.id"), nullable=False)

    configuration = db.relationship("Configuration")

    def __repr__(self):
        return f"<WaterLog {self.date} +{self.volume_ml}ml>"
