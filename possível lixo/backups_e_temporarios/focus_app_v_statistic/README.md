# FOCUS

Documentação técnica oficial do estado **atual** da aplicação FOCUS. Este documento foi escrito a partir de uma inspeção direta do código existente — não descreve o manual de implementação nem o roadmap conceitual, apenas o que está de fato implementado e funcionando.

---

## 1. Objetivo da aplicação

FOCUS é uma aplicação pessoal de ciclos de foco no estilo Pomodoro. O cronômetro em si é só o mecanismo operacional; o que a aplicação registra e apresenta é o **progresso acumulado** desse tempo de foco, através de:

- **Progresso diário** (mínimo e ideal) — metas de ciclos por dia;
- **Progresso extraordinário** — esforço além da meta ideal do dia, que só passa a existir depois que a meta ideal é atingida;
- **Progresso semanal** — meta de ciclos por semana;
- **Progresso absoluto** — um objetivo de longo prazo (ex.: "1000 ciclos"), sem prazo, que fica ativo até ser concluído;
- **Recompensas** vinculadas a esses progressos, com histórico de quantas vezes e quando foram conquistadas;
- **Estatísticas** derivadas dos ciclos concluídos, comparando o período atual com o anterior;
- **Calendário de atividade**, com intensidade por ciclos ou por minutos;
- **Hidratação**, registrada manualmente em garrafas;
- **Configuração histórica** — qualquer alteração de parâmetro (duração do foco, metas, etc.) gera uma nova versão da configuração, preservando o contexto de tudo que já foi registrado.

A regra conceitual central do sistema, e a que mais condiciona a arquitetura do código, é:

> **Ciclo é a unidade operacional. Minuto é a unidade de medida.**

Um ciclo concluído carrega, gravada nele mesmo, a duração que tinha *quando foi criado* — não a duração configurada hoje. Isso permite que o usuário aumente a duração do foco ao longo do tempo sem que isso reescreva silenciosamente o histórico.

A filosofia de produto (tal como reflete o código: ausência de XP, níveis, rankings ou qualquer elemento social) é a de registrar o que realmente aconteceu e deixar que o crescimento dos números — ciclos, minutos, dias ativos — seja o próprio incentivo, sem gamificação artificial.

---

## 2. Stack tecnológica

| Camada | Tecnologia | Observação |
|---|---|---|
| Linguagem | Python 3.12 | testado com 3.12.3 |
| Framework web | Flask 3.1 | `Flask>=3.1` em `requirements.txt` |
| Banco de dados | SQLite | arquivo único em `instance/focus.db` |
| ORM | Flask-SQLAlchemy 3.1 | `db = SQLAlchemy()` em `app/extensions.py` |
| Sistema de migrações | **nenhum, apesar de listado** | ver nota abaixo |
| Frontend | Jinja2 (HTML server-rendered) | sem framework JS |
| JavaScript | JavaScript puro (vanilla), sem build step | `app/static/js/*.js` |
| Fontes | Poppins e Lora, self-hosted em `.woff2` | ver seção 13 |
| CSS | folha única `app/static/css/style.css`, sem pré-processador | variáveis CSS nativas (`--var`) |

**Nota sobre migrações:** `Flask-Migrate>=4.0` está listado em `requirements.txt`, mas **não é inicializado em nenhum lugar do código** — não existe `Migrate(app, db)` em `app/__init__.py`, nem pasta `migrations/`. O schema é criado inteiramente por `db.create_all()`, chamado pelos comandos de CLI (`init-db`, `reset-db`, `seed-demo`). Isso significa que **não há suporte real a alterações incrementais de schema** no estado atual — qualquer mudança de modelo exige recriar o banco do zero (ver seção 16).

Dependências completas (`requirements.txt`):
```text
Flask>=3.1
Flask-SQLAlchemy>=3.1
Flask-Migrate>=4.0
```

---

## 3. Estrutura de diretórios

```text
.
├── app/
│   ├── __init__.py          # application factory (create_app), registra blueprints e CLI
│   ├── cli.py                # comandos flask: init-db, reset-db, seed-demo, shell-info
│   ├── extensions.py         # instância única do SQLAlchemy (db)
│   ├── models.py             # todas as entidades (13 modelos)
│   │
│   ├── services/              # regras de negócio — nenhuma rota acessa o db diretamente
│   │   ├── config_service.py     # vigência de Configuration
│   │   ├── cycles_service.py     # ciclo de vida de Session / FocusCycle / RestCycle
│   │   ├── progress_service.py   # leitura de snapshots + motor de progresso
│   │   ├── engine.py             # motor de conclusão de ciclo (único ponto de entrada)
│   │   ├── rewards_service.py    # registro de RewardAchievement
│   │   ├── stats_service.py      # agregações derivadas (semana/mês, comparação)
│   │   ├── calendar_service.py   # grade de atividade (heatmap)
│   │   ├── water_service.py      # hidratação + mensagens pós-ciclo
│   │   └── wishlist_service.py   # ativação de item da wishlist -> AbsoluteProgress
│   │
│   ├── routes/                # blueprints Flask (view functions finas, sem regra de negócio)
│   │   ├── main.py               # "/" — Home
│   │   ├── api.py                # "/api/*" — endpoints JSON usados pelo timer/calendário/água
│   │   ├── stats.py              # "/estatisticas"
│   │   ├── rewards.py            # "/recompensas"
│   │   └── settings.py           # "/configuracoes"
│   │
│   ├── templates/              # Jinja2, um arquivo por página + base.html
│   │   ├── base.html             # layout com sidebar
│   │   ├── home.html
│   │   ├── stats.html
│   │   ├── rewards.html
│   │   └── settings.html
│   │
│   └── static/
│       ├── css/style.css        # design system inteiro em um único arquivo
│       ├── js/
│       │   ├── timer.js            # máquina de estados do cronômetro (idle → focusing → ... )
│       │   ├── calendar.js         # toggle + fetch do heatmap
│       │   └── water.js            # botão "+1 garrafa"
│       └── fonts/
│           ├── poppins/            # pesos 300, 400, 500 (.woff2)
│           └── lora/               # pesos 500, 600, 700 (.woff2)
│
├── instance/
│   └── focus.db               # banco SQLite (criado em runtime, fora do controle de versão)
├── config.py                  # classe Config (SECRET_KEY, SQLALCHEMY_DATABASE_URI, ...)
├── run.py                     # ponto de entrada (`app = create_app()`)
├── requirements.txt
└── .gitignore
```

Não existem, no projeto atual: pasta `tests/`, pasta `migrations/`, arquivo `.env`/`.flaskenv`, Dockerfile, ou qualquer configuração de CI.

---

## 4. Arquitetura de dados

Todas as entidades estão em `app/models.py`, herdando um `TimestampMixin` (`created_at`/`updated_at`). Nenhuma agrega estado calculável de outra — quando um valor pode ser derivado de `FocusCycle`, ele é sempre derivado por query (nunca guardado como campo redundante), exceto os contadores de progresso descritos abaixo, que **são** persistidos porque representam o próprio estado do progresso, não uma estatística.

| Entidade | Tipo de dado | Papel |
|---|---|---|
| `Configuration` | primário, versionado | pacote de parâmetros vigente num período |
| `Session` | primário | agrupamento de ciclos de um período de trabalho |
| `FocusCycle` | primário (com snapshot) | um ciclo de foco, unidade operacional |
| `RestCycle` | primário (com snapshot) | um ciclo de descanso |
| `DailyMinimumProgress` | derivado, persistido | estado do progresso mínimo do dia |
| `DailyIdealProgress` | derivado, persistido | estado do progresso ideal do dia |
| `ExtraordinaryProgress` | derivado, persistido | esforço além do ideal — só existe após desbloqueio |
| `WeeklyProgress` | derivado, persistido | estado do progresso semanal |
| `AbsoluteProgress` | primário (meta definida pelo usuário) | objetivo de longo prazo |
| `WishlistItem` | primário | candidato a objetivo absoluto, ainda não ativado |
| `Reward` | primário | definição de uma recompensa |
| `RewardAchievement` | histórico | um registro por vez que uma recompensa foi conquistada |
| `WaterLog` | primário (com snapshot) | um registro manual de garrafa consumida |

### `Configuration`

Campos: `valid_from`, `valid_to` (`None` = vigente), `focus_minutes`, `short_break_minutes`, `long_break_minutes`, `cycles_per_session`, `daily_minimum_goal`, `daily_ideal_goal`, `weekly_goal`, `water_bottle_ml`, `water_goal_ml`, `theme`, `primary_color`.

Todos os parâmetros configuráveis do sistema — pomodoro, metas, hidratação e aparência — vivem numa única entidade versionada, em vez de tabelas de vigência separadas por domínio. Isso reflete uma decisão de projeto documentada no próprio código (`app/models.py`, docstring de `Configuration`): o produto sempre trata mudança de configuração como troca de um "pacote" inteiro, não de parâmetros isolados.

### `Session`

`date`, `started_at`, `ended_at` (nullable), `status` (`active` | `ended`). Um dia pode ter várias sessões. Relaciona-se com `FocusCycle` e `RestCycle` via `session_id`.

### `FocusCycle`

`session_id`, `configuration_id`, `started_at`, `completed_at`, **`focus_duration_minutes`** (snapshot imutável, copiado de `Configuration.focus_minutes` no momento em que o ciclo é criado), `title` (opcional), `status` (`started` | `completed` | `abandoned`).

Só ciclos com `status == "completed"` entram em qualquer contagem — progresso, estatística, calendário.

### `RestCycle`

Mesma lógica de `FocusCycle`: `kind` (`short` | `long`), `duration_minutes` (snapshot de `short_break_minutes`/`long_break_minutes`), `status` (`started` | `completed` | `abandoned`).

### `DailyMinimumProgress` / `DailyIdealProgress`

Uma linha por `date` (`unique=True`). Campos: `goal` (snapshot da meta vigente **no momento em que o primeiro ciclo do dia foi concluído**, não no início do dia), `current_count`, `status` (`pending` | `completed`), `completed_at`.

### `ExtraordinaryProgress`

Uma linha por `date`. **A existência da linha é o próprio estado "desbloqueado"** — não há um campo booleano separado. Ela só é criada no primeiro ciclo concluído *depois* de `DailyIdealProgress` já estar `completed`. Campos: `extra_cycles`, `extra_minutes`, `daily_ideal_id` (FK), `configuration_id`.

### `WeeklyProgress`

Uma linha por `(week_start, week_end)` (constraint única). Semana calculada como segunda a domingo. Mesma estrutura de `goal`/`current_count`/`status` dos progressos diários.

### `AbsoluteProgress`

`title`, `description`, `goal_cycles`, `current_count`, `started_at`, `completed_at`, `status` (`active` | `completed`), `wishlist_item_id` (nullable — presente quando o objetivo nasceu de um item de wishlist ativado). Não tem data de expiração nem reset: permanece `active` até `current_count >= goal_cycles`, e para de acumular depois disso (`current_count` é travado em `goal_cycles`).

### `WishlistItem`

`title`, `description`, `suggested_goal`, `order`, `status` (`wishlist` | `activated`). Não é progresso — apenas um catálogo de futuros objetivos absolutos.

### `Reward`

`title`, `description`, `progress_type` (`daily_minimum` | `daily_ideal` | `weekly` | `absolute`), `absolute_progress_id` (nullable, usado só quando `progress_type == "absolute"`), `active`.

### `RewardAchievement`

`reward_id`, `achieved_date`, `start_date`/`end_date` (nullable — usados para recompensas de período, ex. "Praia: 06/08 → 09/08"; no código atual, nenhuma rota preenche esses dois campos para recompensas diárias, só para as semanais, via `weekly.week_start`/`week_end`).

### `WaterLog`

`date`, `logged_at`, `volume_ml` (snapshot de `Configuration.water_bottle_ml` no momento do registro), `configuration_id`.

### A regra ciclo ≠ minuto, na prática

```text
Configuration A (valid_from=01/08, valid_to=10/08): focus_minutes = 35
Configuration B (valid_from=11/08, valid_to=None):   focus_minutes = 45

FocusCycle #1..#8   -> configuration_id = A.id -> focus_duration_minutes = 35 (fixo, para sempre)
FocusCycle #9..#11  -> configuration_id = B.id -> focus_duration_minutes = 45 (fixo, para sempre)
```

Isso foi verificado diretamente no banco durante o desenvolvimento (não é apenas uma intenção de design):

```text
durations por ciclo: [35, 35, 35, 35, 35, 35, 35, 35, 45, 45, 45]
```

Nenhuma consulta do sistema (estatísticas, calendário, progresso) recalcula esse valor — todas leem `FocusCycle.focus_duration_minutes` diretamente.

---

## 5. Configuração histórica

Implementada em `app/services/config_service.py`, com três funções:

- **`get_current_configuration()`** — retorna a linha com `valid_to IS NULL`. Se não existir nenhuma (banco vazio, cenário que não deveria ocorrer fora de testes), cria uma com os valores default do modelo.
- **`update_configuration(**changes)`** — fecha a configuração vigente (`valid_to = agora`) e cria uma nova linha, copiando todos os campos da anterior e sobrescrevendo apenas os que vieram em `changes`.
- **`configuration_history(limit=20)`** — lista as configurações mais recentes primeiro, usada pela tela de Configurações.

**Comportamento real observado, não documentado no manual original:** `update_configuration()` **sempre** cria uma nova versão quando chamada, mesmo que nenhum valor tenha efetivamente mudado. A rota `POST /configuracoes` chama essa função a cada submit do formulário — inclusive se o usuário só reabrir a página e clicar "Salvar" sem alterar nada. Isso significa que o histórico de configuração pode acumular versões idênticas entre si. Não há verificação de diff antes de criar uma nova linha.

Como cada domínio de parâmetro é afetado:

| Parâmetro | Efeito ao mudar |
|---|---|
| Duração do foco | Novos `FocusCycle` usam o novo valor; ciclos já concluídos mantêm o valor antigo (snapshot) |
| Pausa curta / longa | Mesmo comportamento de snapshot, aplicado a `RestCycle` |
| Ciclos por sessão | Usado só no frontend (`timer.js`) para sugerir pausa curta vs. longa — não há enforcement no backend |
| Metas (mínima/ideal/semanal) | A meta de uma instância de progresso (`DailyMinimumProgress`, etc.) é fixada no momento em que essa instância é criada — ou seja, no primeiro ciclo concluído daquele dia/semana. Mudar a meta no meio do dia **não** afeta o dia já em curso, só o próximo dia/semana que ainda não tem instância criada |
| Hidratação (garrafa/meta) | O volume de cada `WaterLog` é fixado no registro; a meta exibida (`water_goal_ml`) sempre vem da configuração **atual**, não da vigente na data consultada (ver limitação na seção 10) |
| Tema/cor | Aplicado a todo o site instantaneamente na config seguinte, sem impacto em dados |

---

## 6. Fluxo de conclusão de ciclo

Implementado inteiramente em `app/services/engine.py`, função `complete_focus_cycle(cycle_id, title=None)` — chamada exclusivamente pela rota `POST /api/cycles/<id>/complete`.

```text
FocusCycle (status="started")
    │
    ▼
engine.complete_focus_cycle(cycle_id, title)
    │
    ├─ já não está "started"? ──► retorna {"already_processed": True} sem tocar em nada (idempotência)
    │
    ├─ marca completed_at, status="completed", título
    │
    ▼
progress_service.apply_cycle_completion(cycle)
    │
    ├─ 1. DailyMinimumProgress.current_count += 1
    ├─ 2. DailyIdealProgress.current_count += 1
    ├─ 3. ExtraordinaryProgress: cria/incrementa SE o ideal já estava
    │      completo ANTES deste ciclo (o ciclo que fecha o ideal
    │      exatamente na meta não conta como extraordinário)
    ├─ 4. WeeklyProgress.current_count += 1
    └─ 5. AbsoluteProgress ativo (o mais antigo, se houver mais de um):
           current_count += 1, trava em goal_cycles se atingir a meta
    │
    ▼
rewards_service.check_and_register_for_progress(...)
    │  chamado só para as entidades que ACABARAM de virar "completed"
    │  nesta chamada (nunca para as que já estavam completas)
    │
    ▼
db.session.commit()   ← commit único
    │
    ▼
retorna JSON com: daily_minimum_just_completed, daily_ideal_just_completed,
  extraordinary_just_unlocked, extraordinary_cycles, weekly_just_completed,
  absolute_just_completed, rewards_achieved[], post_cycle_message
```

**Idempotência:** garantida por checar `cycle.status != "started"` antes de qualquer efeito colateral. Chamar `/complete` duas vezes para o mesmo `cycle_id` na segunda vez retorna `{"ok": True, "already_processed": True, "status": "completed"}` sem incrementar nada. Isso foi testado diretamente (ver seção 17).

**Transação:** todo o bloco (marcar ciclo, atualizar os 5 tipos de progresso, registrar recompensas) roda entre um único `db.session.flush()`/`commit()`. Se qualquer parte lançar uma exceção, há `db.session.rollback()` no `except` e a exceção é **relançada** (`raise`) — isto é, o Flask não a captura, e a rota `POST /api/cycles/<id>/complete` responde com um erro 500 padrão do Flask (página HTML de erro, não um JSON estruturado). Não existe tratamento específico de erro nessa rota.

**O que é persistido:** o `FocusCycle` marcado como `completed`, as linhas de progresso atualizadas/criadas, e as `RewardAchievement` criadas. **O que é derivado:** tudo que aparece em Estatísticas e Calendário — nada ali é escrito por este fluxo, é sempre recalculado por query.

---

## 7. Progressos

#### Diário mínimo (`DailyMinimumProgress`)

Objetivo: sinalizar que o usuário "trabalhou" naquele dia. Uma linha nova por `date`, criada sob demanda no primeiro ciclo concluído do dia — nunca preventivamente. Meta (`goal`) fixada nesse momento. Não há job ou rotina que "reseta" a entidade à meia-noite: o reset é implícito, porque o dia seguinte simplesmente ainda não tem linha, e a próxima leitura cria uma nova.

#### Diário ideal (`DailyIdealProgress`)

Mesma estrutura do mínimo, com uma meta maior. Independente do mínimo — os dois são incrementados juntos a cada ciclo concluído, mas cada um tem seu próprio `goal`/`status`/`completed_at`. Não há relação de dependência entre eles no código (o ideal pode, em tese, completar antes do mínimo, se a meta mínima for maior que a ideal — o sistema não impede essa configuração).

#### Extraordinário (`ExtraordinaryProgress`)

Só passa a existir depois que `DailyIdealProgress.status == "completed"`. O ciclo que faz o `current_count` do ideal atingir exatamente a meta **não** conta como extraordinário — só o próximo ciclo em diante. Cada ciclo extraordinário soma `+1` a `extra_cycles` e `+focus_duration_minutes` a `extra_minutes`. Reseta implicitamente todo dia, pelo mesmo mecanismo do mínimo/ideal (nova `date`, linha inexistente até o primeiro ciclo excedente daquele dia).

#### Semanal (`WeeklyProgress`)

Período: segunda a domingo (`week_bounds()` em `progress_service.py`). Uma linha por `(week_start, week_end)`. Meta e conclusão seguem o mesmo padrão do diário. Reset implícito na virada de semana.

#### Absoluto (`AbsoluteProgress`)

Não tem período — fica `active` indefinidamente até `current_count` atingir `goal_cycles`, quando vira `completed` e para de receber incrementos. **Limitação observada:** `progress_service.get_active_absolute()` sempre retorna o `AbsoluteProgress` `active` mais antigo (`order_by(started_at.asc())`), e é só ele que recebe incrementos a cada ciclo. Nada no código impede a existência de mais de um `AbsoluteProgress` com `status="active"` simultaneamente — a interface (`rewards.html`) desabilita o botão "ATIVAR" quando já existe um ativo, mas essa é uma checagem só do lado do template, não da rota `POST /recompensas/wishlist/<id>/ativar`, que não valida isso no servidor.

---

## 8. Recompensas

`Reward` é a definição (título + a qual tipo de progresso está vinculada); `RewardAchievement` é o histórico de conquistas.

O registro de uma conquista acontece exclusivamente dentro do motor de conclusão (`engine.py`), e só quando a entidade de progresso correspondente **acabou de** transicionar para `completed` nesta chamada — nunca porque ela "está" completa. Isso evita duplicar uma recompensa em ciclos subsequentes do mesmo dia/semana.

`rewards_service.check_and_register_for_progress()` busca todas as `Reward` ativas (`active=True`) daquele `progress_type` e cria uma `RewardAchievement` para cada uma — ou seja, **é possível ter mais de uma recompensa vinculada ao mesmo tipo de progresso**, e todas são conquistadas juntas quando esse progresso completa (não há limite de uma recompensa por tipo no modelo).

Repetição: cada conclusão gera uma nova linha em `RewardAchievement`; a página de Recompensas mostra `len(reward.achievements)` como "quantas vezes" e a data do último elemento da lista como "última conquista".

Datas de período (`start_date`/`end_date`): só preenchidas para recompensas do tipo `weekly` (usando `WeeklyProgress.week_start`/`week_end`). Recompensas `daily_minimum`, `daily_ideal` e `absolute` só recebem `achieved_date` — o template `rewards.html` não exibe `start_date`/`end_date` de forma alguma, então essa informação, mesmo quando presente no banco, não aparece na interface atual.

---

## 9. Estatísticas

Implementadas em `app/services/stats_service.py`, expostas em `GET /estatisticas`. Tudo é calculado por query no momento da requisição — nenhum valor é pré-agregado ou cacheado.

Disponível hoje:

- `cycles_count(start, end)` — `COUNT` de `FocusCycle` concluídos no intervalo;
- `minutes_sum(start, end)` — `SUM(focus_duration_minutes)` no intervalo (nunca `count * config_atual`);
- `active_days_count(start, end)` — `COUNT(DISTINCT Session.date)`, independente de quantos ciclos houve naquele dia;
- `sessions_count`, `extraordinary_totals` (ciclos e minutos extraordinários somados), `rewards_achieved_count`, `best_day` (dia com mais ciclos no período);
- **comparação com o período anterior**, calculada separadamente para ciclos e para minutos (`_growth_pct`), com uma regra explícita: se o período anterior teve `0`, o percentual retorna `None` em vez de inventar um número — o template `stats.html` simplesmente omite a linha de crescimento nesse caso;
- alternância **semana / mês** via `?period=week` ou `?period=month` na URL — implementada como dois cálculos distintos (`weekly_stats()` e `monthly_stats()`), não um único cálculo genérico por intervalo.

### Como uma semana com duas configurações diferentes é representada — estado real

`configurations_in_period(start, end)` retorna a lista de todas as `Configuration` que estiveram vigentes em algum momento do intervalo (usando sobreposição de `valid_from`/`valid_to` com o período). O template renderiza essa lista como uma linha de contexto:

```text
Configuração vigente no período: 35 min/ciclo (meta ideal 8) · 45 min/ciclo (meta ideal 9)
```

**Isto é uma implementação parcial, e deve ser tratado como pendência, não como recurso completo:** a lista mostra *quais* configurações estiveram ativas no período, mas **não decompõe** quantos ciclos ou minutos vieram de cada uma. Ou seja, o sistema não produz uma frase como "8 ciclos a 35 min + 3 ciclos a 45 min = 415 min" automaticamente — ele mostra `cycles_count` e `minutes_sum` agregados do período inteiro, mais a lista separada de configurações que existiram nele. Cruzar as duas informações manualmente (ex.: qual configuração produziu quantos ciclos) exigiria uma consulta adicional que não existe hoje.

### Calendário

`app/services/calendar_service.py`. `daily_activity(start, end)` agrupa `FocusCycle` concluídos por dia via `GROUP BY date(completed_at)`, retornando ciclos e minutos por dia. `heatmap_grid(weeks, mode)` monta uma grade de `weeks` colunas × 7 linhas e calcula um nível de intensidade 0–4 por quantil simples sobre os dias com atividade no próprio período consultado (não é uma escala fixa global). Exposto via `GET /api/calendar?mode=cycles|minutes&weeks=N`, consumido por `app/static/js/calendar.js`, que só é carregado (e só tem os elementos DOM necessários) na página Home — o ícone "atividade" da sidebar não faz nada nas outras páginas.

---

## 10. Hidratação

`app/services/water_service.py`.

- **Capacidade da garrafa** e **meta diária** vivem em `Configuration.water_bottle_ml` / `Configuration.water_goal_ml`, editáveis em Configurações.
- **Registro manual**: `POST /api/water/log` cria um `WaterLog` com `volume_ml` igual ao `water_bottle_ml` **vigente no momento do clique** (snapshot, não recalculado depois).
- **Cálculo acumulado**: `daily_total_ml(d)` soma todos os `WaterLog.volume_ml` daquele dia — corretamente resiliente a mudanças de tamanho de garrafa no meio do dia, porque cada registro já carrega seu próprio volume.
- **Apresentação em litros**: `daily_summary(d)` retorna `total_ml`, `total_l` (arredondado a 2 casas), `goal_ml`, `goal_l`, `bottle_ml`, `bottles_logged` (divisão inteira), `bottles_to_goal` (divisão real, sem arredondar para cima) e `pct`.

**Limitação observada:** `daily_summary(d)` usa `get_current_configuration()` para `goal_ml`/`bottle_ml` — ou seja, a meta e o tamanho de garrafa exibidos **são sempre os atuais**, não os vigentes na data `d` consultada. Na prática isso não é visível hoje porque a única chamada existente no código é sempre para a data de hoje (`date.today()`, em `main.py` e `api.py`) — mas a função, se reaproveitada para exibir hidratação de um dia passado, mostraria a meta errada. Não há relação com estatísticas: hidratação não aparece em `stats_service.py` nem na página de Estatísticas.

---

## 11. API

Todas as rotas abaixo existem em `app/routes/`. Nenhuma tem autenticação — o projeto assume um único usuário local.

### `app/routes/main.py`

| Método | Rota | Finalidade |
|---|---|---|
| GET | `/` | Renderiza a Home com o estado do dia (mínimo, ideal, extraordinário se existir, semanal, absoluto ativo, água) |

### `app/routes/api.py` (prefixo `/api`)

| Método | Rota | Corpo esperado | Resposta | Efeito |
|---|---|---|---|---|
| GET | `/api/home-state` | — | JSON com `daily_minimum`, `daily_ideal`, `extraordinary` (ou `null`), `weekly`, `absolute` (ou `null`), `water` | leitura, sem efeito |
| POST | `/api/cycles/start` | — | `{cycle_id, focus_duration_minutes, started_at}` | cria `Session` (se não houver ativa) + `FocusCycle` com `status="started"` |
| POST | `/api/cycles/<id>/complete` | `{"title": "..."}` (opcional) | ver seção 6 | motor de conclusão completo; a chave `home_state` (mesmo payload de `/api/home-state`) é sempre anexada à resposta, inclusive quando `id` não existe; **erro 500 sem JSON se algo falhar internamente**; `{"ok": False, "error": "...", "home_state": {...}}` (HTTP 200) se `id` não existir |
| POST | `/api/cycles/<id>/abandon` | — | `{ok, status}` | marca `status="abandoned"` só se ainda `started`; idempotente por não fazer nada se já não estiver `started` |
| POST | `/api/rest/start` | `{"kind": "short"|"long"}` | `{rest_id, kind, duration_minutes}` | cria `RestCycle` |
| POST | `/api/rest/<id>/complete` | — | `{ok}` | marca `status="completed"` |
| POST | `/api/rest/<id>/abandon` | — | `{ok}` | marca `status="abandoned"` |
| POST | `/api/water/log` | — | `daily_summary()` do dia | cria `WaterLog` |
| GET | `/api/calendar` | query params `mode` (`cycles`\|`minutes`, default `cycles`) e `weeks` (default `18`) | `{mode, weeks, grid}` | leitura, sem efeito |

Nenhum desses endpoints usa códigos de status HTTP diferentes de 200 para erros de aplicação (ex.: ciclo inexistente) — o corpo JSON é que indica sucesso/falha via a chave `ok`. Erros não tratados (exceções) resultam no 500 padrão do Flask.

### `app/routes/stats.py`

| Método | Rota | Query params | Finalidade |
|---|---|---|---|
| GET | `/estatisticas` | `period` (`week` \| `month`, default `week`) | Renderiza estatísticas do período |

### `app/routes/rewards.py`

| Método | Rota | Finalidade |
|---|---|---|
| GET | `/recompensas` | Lista recompensas ativas com conquistas, wishlist, objetivo absoluto ativo |
| POST | `/recompensas/wishlist/<item_id>/ativar` | Ativa um item da wishlist (cria `AbsoluteProgress`), redireciona para `/recompensas` |

### `app/routes/settings.py`

| Método | Rota | Finalidade |
|---|---|---|
| GET | `/configuracoes` | Formulário de configuração + histórico de vigência + wishlist + recompensas cadastradas |
| POST | `/configuracoes` | Cria uma nova versão de `Configuration` (sempre, mesmo sem mudanças reais — ver seção 5) |
| POST | `/configuracoes/wishlist` | Cria um `WishlistItem` (campos `title`, `suggested_goal`) |
| POST | `/configuracoes/recompensas` | Cria uma `Reward` (campos `title`, `progress_type`) |

---

## 12. Interface

Páginas existentes, todas herdando `templates/base.html` (sidebar + `<link>` do CSS único):

- **Home (`/`)** — as quatro barras de progresso do dia/semana/objetivo empilhadas e centralizadas, cronômetro, atalho de hidratação, e o calendário de atividade (oculto por padrão, revelado pelo ícone da sidebar). É a única página com o timer funcional e com JS de calendário/água carregado.
- **Estatísticas (`/estatisticas`)** — cartões de ciclos, minutos, dias ativos e extraordinários, com percentual de crescimento vs. período anterior; alternância semana/mês por link (recarrega a página, não é AJAX); linha de contexto com as configurações vigentes no período.
- **Recompensas (`/recompensas`)** — lista de recompensas conquistadas com contagem e data, barra do objetivo absoluto ativo (se houver), e a wishlist com botão de ativação.
- **Configurações (`/configuracoes`)** — formulário único para todos os parâmetros de `Configuration`, histórico de vigência (lista, sem paginação), formulário inline para adicionar itens de wishlist, formulário inline para adicionar recompensas.

Não existem páginas dedicadas a "calendário" ou "hidratação" como rotas separadas — ambos são seções dentro da Home (o calendário como painel expansível, a hidratação como uma linha simples com botão).

**Sidebar** (`base.html`): quatro ícones fixos (Home, Atividade, Estatísticas, Recompensas) e um quinto (Configurações) fixado ao fundo via `.sidebar-bottom`. O ícone "Atividade" não navega — só dispara o JS de toggle do calendário, e só tem efeito na Home (ver seção 9). O item ativo na sidebar é destacado comparando `request.endpoint` no Jinja.

---

## 13. Identidade visual

Implementada em `app/static/css/style.css`, com variáveis CSS (`:root` para o tema claro, `[data-theme="dark"]` para o escuro — o atributo `data-theme` é escrito no `<html>` por `base.html`, lendo `cfg.theme`).

- **Dark mode**: tema padrão (`Configuration.theme` default `"dark"`); implementado como conjunto próprio de variáveis, não como inversão automática do tema claro.
- **Bug verificado — tema inconsistente entre páginas**: `base.html` lê o tema via `data-theme="{{ (cfg.theme if cfg is defined else 'dark') }}"`, mas **apenas as rotas de Home (`main.py`) e Configurações (`settings.py`) passam `cfg` para o template**. `app/routes/stats.py` e `app/routes/rewards.py` chamam `render_template(...)` sem a variável `cfg`, então `cfg is defined` é `False` nessas páginas e o tema cai sempre no fallback `"dark"` — **mesmo que o usuário tenha salvo `theme = "light"`**. Verificado diretamente: com o tema salvo como `light`, `/` e `/configuracoes` respondem `data-theme="light"`, enquanto `/estatisticas` e `/recompensas` respondem `data-theme="dark"`.
- **Geometria**: `border-radius` não é usado em nenhum componente principal (barras, botões, cartões de estatística) — bordas retas de 2px (`border:2px solid var(--text)`), com sombra sólida deslocada (`box-shadow: 3px 3px 0 var(--border)`) em vez de blur.
- **Barras de progresso** (`.bartrack`/`.barfill`): altura fixa de 22px, preenchimento com um padrão `repeating-linear-gradient` que cria segmentos visuais (efeito "blocos"), largura fixa de 320px centralizada (`.barblock`), nunca esticada à largura da tela.
- **Hierarquia numérica**: todos os números centrais (contagens de progresso, cronômetro) usam a classe `.num`, que aplica a fonte serifada Lora com `font-variant-numeric: lining-nums tabular-nums` — os algarismos não deslocam o texto ao redor quando mudam de valor.
- **Tipografia**: Poppins (300/400/500) para toda a interface — labels, botões, texto corrido; Lora (500/600/700) só para números. Ambas self-hosted via `@font-face` apontando para `/static/fonts/...`, sem dependência de CDN externo.
- **Cores**: paleta curta e nomeada por função em variáveis CSS — `--primary` (verde, progresso normal), `--extra` (dourado, extraordinário), `--alert` (vermelho, erros/deltas negativos), `--text`/`--text2`/`--text3` (hierarquia de texto), `--border`, `--surface`/`--surface2`.
- **Responsividade**: um único `@media (max-width: 720px)` no fim do CSS, que reduz paddings, empilha `.stat-grid` e `.settings-grid` em menos colunas, reduz o tamanho do número do cronômetro e limita a largura das barras a 100%.

---

## 14. Como instalar

Pré-requisitos: Python 3.12 (ou compatível — o projeto não usa nenhuma sintaxe específica de 3.12 além de `X | None` em type hints, que funciona a partir do 3.10).

```bash
# 1. clonar/extrair o projeto e entrar na pasta
cd focus

# 2. criar e ativar o ambiente virtual
python3 -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate         # Windows

# 3. instalar dependências
pip install -r requirements.txt

# 4. (opcional) variáveis de ambiente — nenhuma é obrigatória.
#    SECRET_KEY e DATABASE_URL têm defaults em config.py e funcionam
#    out-of-the-box para desenvolvimento local.
export SECRET_KEY="troque-em-producao"          # opcional
export DATABASE_URL="sqlite:///instance/focus.db"  # opcional, já é o default

# 5. inicializar o banco (cria as tabelas + Configuration inicial)
flask --app run.py init-db
```

Não há passo de migrações porque não há sistema de migrações configurado (seção 2). Não há passo de build de frontend (sem `npm install`/`package.json` no projeto entregue — as fontes já vêm compiladas em `.woff2` dentro de `app/static/fonts/`).

Seed opcional para ver dados de exemplo:

```bash
flask --app run.py seed-demo
```

---

## 15. Como executar

```bash
flask --app run.py run
```

- Endereço padrão: `http://127.0.0.1:5000`
- Porta customizada: `flask --app run.py run --port 5055`
- Modo desenvolvimento (reload automático + debugger): `flask --app run.py run --debug`, ou definir `app.run(debug=True)` — já presente em `run.py` quando executado diretamente com `python3 run.py` (`if __name__ == "__main__": app.run(debug=True)`)

Para checar se está funcionando, abra a Home no navegador ou:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5000/
# 200
```

---

## 16. Banco de dados

- **SGBD**: SQLite.
- **Localização do arquivo**: `instance/focus.db`, caminho resolvido em `config.py` (`BASE_DIR/instance/focus.db`), sobrescrevível pela variável `DATABASE_URL`.
- **Criar**: `flask --app run.py init-db` — chama `db.create_all()` e garante uma `Configuration` inicial se não existir nenhuma vigente.
- **Resetar**: `flask --app run.py reset-db` — pede confirmação interativa (`click.confirm`), depois `db.drop_all()` + `db.create_all()`. **Apaga todos os dados**, sem criar uma `Configuration` inicial automaticamente (é preciso rodar `init-db` de novo, ou `seed-demo`, em seguida).
- **Migrações**: não existem (seção 2). Qualquer mudança em `app/models.py` exige recriar o banco (`reset-db` + `init-db`) em desenvolvimento; não há caminho de upgrade para um banco com dados reais.
- **Seed**: `flask --app run.py seed-demo` — cria duas `Configuration` (35min e 45min), 11 `FocusCycle` concluídos (8 na config antiga, 3 na nova, sendo estes últimos os extraordinários), progresso diário mínimo/ideal já completos, uma `ExtraordinaryProgress` com `+3`, uma `WeeklyProgress`, um `AbsoluteProgress` ("MP3", 734/1000), uma `Reward` com uma `RewardAchievement`, e três `WaterLog`. **Importante:** este comando grava os registros diretamente via SQLAlchemy — ele **não** passa pelo motor de conclusão (`engine.py`). É uma fixture para inspecionar o schema populado, não um teste do fluxo real de conclusão de ciclo.
- **Comandos CLI disponíveis** (todos em `app/cli.py`, registrados em `register_cli()`):

| Comando | O que faz |
|---|---|
| `flask --app run.py init-db` | cria tabelas + configuração inicial |
| `flask --app run.py reset-db` | apaga tudo e recria (com confirmação) |
| `flask --app run.py seed-demo` | popula dados de demonstração, direto no banco |
| `flask --app run.py shell-info` | imprime a contagem de linhas de cada tabela |

---

## 17. Testes

**Não existe suíte de testes automatizados no projeto** — não há pasta `tests/`, nem `pytest` nas dependências, nem `unittest`. Toda a validação até agora foi manual/scriptada durante o desenvolvimento, usando o `test_client()` do Flask e, para o fluxo do timer, o Playwright controlando um navegador real contra o servidor de desenvolvimento. Esses scripts não ficaram salvos no projeto — foram executados ad-hoc e descartados.

Cenários que foram verificados dessa forma (não são testes que rodam automaticamente hoje):

- **Idempotência**: chamar `POST /api/cycles/<id>/complete` duas vezes para o mesmo ciclo — confirmado que a segunda chamada retorna `already_processed: true` sem incrementar `daily_minimum`/`daily_ideal`/etc.
- **Mudança de configuração**: alterar `focus_minutes` de 35 para 45 no meio de uma sequência de ciclos e conferir que os ciclos antigos mantêm `focus_duration_minutes = 35` e os novos passam a ter `45`.
- **Snapshot de duração**: consulta direta ao banco (`FocusCycle.focus_duration_minutes` por ciclo) depois da mudança de configuração acima.
- **Mínimo/ideal**: sequência de ciclos completando a meta mínima antes da ideal, com verificação de `daily_minimum_just_completed`/`daily_ideal_just_completed` nos momentos certos.
- **Extraordinário**: verificado que o ciclo que fecha a meta ideal não é contado como extraordinário, e que o próximo ciclo já é (`extraordinary_just_unlocked: true`, `extraordinary_cycles: 1`), crescendo nos ciclos seguintes.
- **Semanal / absoluto**: incrementados junto com os ciclos diários, sem verificação isolada extensiva além do que o motor de conclusão testado acima já cobre (mesma chamada incrementa os cinco progressos juntos).
- **Fluxo real via UI**: um teste de ponta a ponta com o cronômetro rodando em tempo real (não simulado) — iniciar ciclo, esperar chegar a `00:00`, o modal pós-ciclo abrir sozinho, concluir, e a Home atualizar os números sem reload de página.

Se o projeto crescer, o lugar natural para uma suíte de testes automatizados seria uma pasta `tests/` na raiz, usando `pytest` + o `test_client()` de Flask contra um banco SQLite em memória (`sqlite:///:memory:`) — nenhuma dessas peças existe hoje.

---

## 18. Estado atual

### Implementado

- Modelo de dados completo das 13 entidades, com relacionamentos e snapshots corretos.
- Configuração com vigência histórica (`valid_from`/`valid_to`), aplicada consistentemente a ciclos, descansos e hidratação.
- Motor de conclusão de ciclo único, idempotente, com transação e atualização coordenada de mínimo/ideal/extraordinário/semanal/absoluto/recompensas.
- Extraordinário aparecendo exclusivamente após o ideal completar, com a UI (Home) refletindo isso em tempo real via JS.
- Estatísticas semanais e mensais com comparação percentual separada para ciclos e minutos, e listagem (não decomposição) das configurações vigentes no período.
- Calendário de atividade com dois modos (ciclos/minutos), derivado sempre da mesma fonte.
- Hidratação com snapshot de volume por registro.
- Wishlist → ativação → `AbsoluteProgress`.
- Recompensas com histórico de conquistas.
- Timer funcional no navegador (iniciar/pausar/retomar/parar), fluxo de pausa curta/longa pós-ciclo, tratamento de erro de rede no JS (nunca finge sucesso se a API falhar).
- Tema claro e escuro, aplicados via configuração persistida.
- CLI de desenvolvimento (`init-db`, `reset-db`, `seed-demo`, `shell-info`).

### Parcialmente implementado

- **Estatísticas com múltiplas configurações no período**: mostra quais configurações estiveram vigentes, mas não decompõe ciclos/minutos por configuração dentro do mesmo período (seção 9).
- **Vinculação de recompensa a objetivo absoluto específico**: o campo `Reward.absolute_progress_id` existe e é considerado na busca (`rewards_service.py`), mas não há nenhum formulário na interface (`settings.html`) para o usuário definir esse vínculo ao criar uma recompensa do tipo `absolute` — o campo só pode ser preenchido manualmente no banco.
- **Hidratação para datas passadas**: a função que monta o resumo diário usa a configuração *atual* para meta/tamanho de garrafa, não a vigente na data consultada; hoje isso não é um bug visível porque só é chamada para o dia de hoje.
- **`Session.status`/encerramento**: existe `end_session()` em `cycles_service.py`, mas nenhuma rota ou botão da interface a chama — sessões abertas nunca são marcadas como `ended` no fluxo atual do produto.
- **Tema claro/escuro fora da Home e Configurações**: `stats.html` e `rewards.html` são renderizados sem receber `cfg` do backend, então essas duas páginas sempre exibem `data-theme="dark"`, independentemente do tema salvo pelo usuário. Verificado ao vivo (seção 13).

### Pendente

- Testes automatizados (nenhum existe).
- Sistema de migrações real (Flask-Migrate está listado mas não integrado).
- Autenticação/multiusuário.
- Validação de servidor contra ativação de mais de um `AbsoluteProgress` simultâneo (hoje só a UI desabilita o botão).
- Códigos de status HTTP diferenciados para erros na API (`/api/*` sempre responde 200 nas rotas exceto quando uma exceção não tratada gera 500 automático).
- Tela ou rota dedicada para editar/desativar uma `Reward` existente, ou para desativar um `WishlistItem`.
- Qualquer forma de exportação de dados ou backup além de copiar o arquivo `.db`.

---

## 19. Decisões arquiteturais importantes

Regras que não devem ser quebradas em alterações futuras, todas verificáveis no código atual:

1. **Ciclo ≠ minuto.** `FocusCycle.focus_duration_minutes` nunca é lido de `Configuration.focus_minutes` fora do momento de criação do ciclo.
2. **Duração de ciclo é snapshot.** Vale também para `RestCycle.duration_minutes` e `WaterLog.volume_ml`.
3. **`Configuration` tem vigência histórica.** Nunca editar `focus_minutes` (ou qualquer campo) de uma linha existente — sempre fechar `valid_to` e criar uma nova via `update_configuration()`.
4. **Histórico nunca é recalculado com a configuração atual.** Toda soma de minutos usa `SUM(FocusCycle.focus_duration_minutes)`, nunca `COUNT(*) * configuration_atual.focus_minutes`.
5. **Conclusão de ciclo é idempotente.** Qualquer nova lógica adicionada a `engine.complete_focus_cycle` deve respeitar o guard `if cycle.status != "started": return`.
6. **Um único motor coordena a conclusão.** Nenhuma rota, nenhum script, nenhum outro service deve incrementar `current_count` de uma entidade de progresso fora de `progress_service.apply_cycle_completion`, chamada só por `engine.py`.
7. **Estatísticas derivam dos registros reais.** `stats_service.py` não tem nenhum campo persistido de agregado — se um novo relatório for adicionado, deve seguir o mesmo padrão de `func.sum`/`func.count` em cima de `FocusCycle`.
8. **Extraordinário só aparece após o ideal.** A checagem em `apply_cycle_completion` (`was_ideal_completed_before or (...)`) é o que garante que o ciclo que fecha a meta não é contado como extraordinário — não simplificar essa condição sem revalidar esse caso de borda.
9. **Progresso absoluto termina ao ser concluído.** `current_count` é travado em `goal_cycles` (`absolute.current_count = absolute.goal_cycles`) — nunca deixar passar da meta.
10. **Recompensas são entidades separadas dos progressos.** `Reward.progress_type` é uma string que identifica o tipo, não uma FK direta para `DailyIdealProgress`/etc. — isso é o que permite o título mudar sem quebrar o vínculo estrutural.
11. **Títulos de recompensa podem variar livremente.** Trocar `Reward.title` não afeta `RewardAchievement` já registradas nem a lógica de disparo.
12. **Dados históricos não são alterados retroativamente.** Nenhuma rota faz `UPDATE` em `FocusCycle.focus_duration_minutes`, `Configuration` fechada, ou `RewardAchievement` já criada.

---

## 20. Guia para futuros desenvolvedores

| Quero alterar... | Onde mexer |
|---|---|
| Um campo/entidade do modelo de dados | `app/models.py` — lembrar que não há migrações; qualquer mudança exige `reset-db` + `init-db` em desenvolvimento (seção 16) |
| Regra de negócio de progresso/extraordinário/absoluto | `app/services/progress_service.py`, função `apply_cycle_completion` — **não** duplicar essa lógica em rotas |
| O que acontece ao concluir um ciclo | `app/services/engine.py` — é o único lugar que deveria orquestrar o fluxo completo |
| Regras de recompensa | `app/services/rewards_service.py` |
| Estatísticas ou novos relatórios | `app/services/stats_service.py` — seguir o padrão de agregação por query, nunca armazenar total pré-calculado |
| Endpoints JSON (usados pelo timer/calendário/água) | `app/routes/api.py` |
| Páginas server-rendered | `app/routes/{main,stats,rewards,settings}.py` + template correspondente em `app/templates/` |
| Estilos/identidade visual | `app/static/css/style.css` — arquivo único, variáveis CSS no topo (`:root` e `[data-theme="dark"]`) |
| Comportamento do cronômetro no navegador | `app/static/js/timer.js` — máquina de estados isolada em uma IIFE; qualquer novo estado deve ser adicionado tanto na função `render()` quanto no fluxo de transições |
| Novas configurações (novos parâmetros editáveis) | Adicionar o campo em `Configuration` (`app/models.py`), incluir na lista `_CONFIG_FIELDS` de `config_service.py` (senão `update_configuration` não vai propagá-lo entre versões), adicionar o campo no formulário `settings.html` e na lista `int_fields` de `routes/settings.py` |
| Novos tipos de recompensa | Hoje `progress_type` é uma string livre validada só na rota (`("daily_minimum", "daily_ideal", "weekly", "absolute")`, em `routes/settings.py` e implicitamente em `rewards_service.py`) — um novo tipo exige atualizar essa validação, o `<select>` em `settings.html`, e o ponto de disparo correspondente em `engine.py` |
| Testes | Não há pasta hoje — criar `tests/` na raiz seguindo o padrão sugerido na seção 17 |

**Arquivos para alterar com cautela, considerando as consequências arquiteturais:**

- `app/services/engine.py` — é o único ponto de entrada para conclusão de ciclo; adicionar um segundo caminho quebra a garantia de idempotência e de fonte única de verdade.
- `app/services/progress_service.py`, especialmente a condição que decide quando o extraordinário nasce — é um caso de borda fácil de quebrar silenciosamente.
- `app/services/config_service.py` — qualquer mudança que passe a *editar* uma `Configuration` existente em vez de versionar quebra a regra central do produto (seção 5, 19).
- `app/models.py`, campos marcados como snapshot (`focus_duration_minutes`, `duration_minutes`, `volume_ml`) — nunca substituir por uma leitura dinâmica de `Configuration`.

---

*Documento gerado a partir de inspeção direta do código em `app/` — não do manual de implementação original. Onde o comportamento real diverge do que estava previsto, a divergência foi documentada explicitamente nas seções acima em vez de omitida.*
