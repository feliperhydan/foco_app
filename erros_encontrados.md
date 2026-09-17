# Relatório de Erros — Sistema Foco
> Análise realizada em 22/08/2026 via inspeção estática de código + testes programáticos com dados reais do banco.

---

## BUG-01 · FocusCycles em `status=started` de dias anteriores jamais são encerrados

**Severidade:** Alta — dados corrompidos permanentemente no banco  
**Arquivos:** [`temporal_service.py`](file:///home/felipe/Área de trabalho/Projetos/Foco/app/services/temporal_service.py) · [`engine.py`](file:///home/felipe/Área de trabalho/Projetos/Foco/app/services/engine.py)

### Descrição
`temporal_service.reconcile_temporal_state()` encerra **sessões** abertas de dias anteriores (seta `Session.status = "ended"`), mas **não abandona** os `FocusCycle` que ficaram em `status="started"` dentro dessas sessões. Esses ciclos ficam permanentemente presos nesse estado — não entram em contagem de progresso, não aparecem na timeline, mas permanecem no banco.

### Evidência (banco de dados real)
```
FocusCycle id=1   session_date=2026-08-18  started_at=2026-08-18 22:59:28  status=started
FocusCycle id=30  session_date=2026-08-21  started_at=2026-08-21 03:31:08  status=started
FocusCycle id=31  session_date=2026-08-21  started_at=2026-08-21 03:31:13  status=started
```
3 ciclos de dias anteriores presos em `started` confirmados via query direta.

### Causa raiz
```python
# temporal_service.py — reconcile_temporal_state()
for session_ in pending_sessions:
    session_.status = "ended"
    session_.ended_at = _end_of_day(session_.date)
    db.session.flush()
    daily_service.consolidate_daily(session_.date, commit=False)
    # ↑ FocusCycles 'started' dentro da session_ NÃO são tocados
```

### Impacto
- Ciclos "zumbis" que podem ser completados via `POST /api/cycles/<id>/complete` mesmo sendo de dias anteriores (ver BUG-04)
- Acúmulo silencioso de registros inconsistentes no banco

---

## BUG-02 · `Daily` consolidados com snapshot desatualizado após operações de debug

**Severidade:** Alta — estatísticas exibem valores errados de forma permanente  
**Arquivos:** [`daily_service.py`](file:///home/felipe/Área de trabalho/Projetos/Foco/app/services/daily_service.py) · [`debug_service.py`](file:///home/felipe/Área de trabalho/Projetos/Foco/app/services/debug_service.py)

### Descrição
Quando `consolidate_daily()` é chamado para um dia, ele seta `consolidated_at` e nunca mais recalcula o snapshot (guard na linha 633: `if daily.consolidated_at is not None: return`). Se dados operacionais forem **criados após a consolidação** (ex: `generate_test_data` injetando `FocusCycle` históricos), o snapshot permanece desatualizado para sempre.

### Evidência (discrepância snapshot vs. banco real)
| Data | Ciclos no snapshot `Daily` | Ciclos reais (`FocusCycle`) |
|------|------|------|
| 2026-08-16 | 5 | 7 |
| 2026-08-17 | 8 | 13 |
| 2026-08-18 | 2 | 10 |
| 2026-08-19 | 3 | 5 |
| 2026-08-20 | 0 | 9 |

5 datas com divergência confirmada. O dia 2026-08-20 tem `session_started=False` no snapshot mas 9 ciclos completados no banco — isso faz o dia ser **excluído de streaks e estatísticas**.

### Causa raiz
```python
# daily_service.py — consolidate_daily()
def consolidate_daily(d: date_, commit: bool = True) -> Daily:
    daily = ensure_daily_for_date(d, ...)
    if daily.consolidated_at is not None:   # ← guard absoluto
        if commit:
            db.session.commit()
        return daily                         # ← retorna sem recalcular
    # ...
```
`debug_service.generate_test_data` injeta `FocusCycle` históricos em datas que já foram consolidadas e não chama um recalculo forçado.

### Impacto
- Página de estatísticas exibe contagens incorretas para períodos históricos
- Streaks calculadas sobre `Daily.session_started` ficam incorretas
- Extraordinários do snapshot diferem dos valores reais (2026-08-17: snapshot=1, real=6; 2026-08-18: snapshot=0, real=1)

---

## BUG-03 · `apply_cycle_completion` atribui progresso ao dia de `completed_at`, não ao dia da sessão

**Severidade:** Média — progresso contabilizado no dia errado em cenários de virada de meia-noite  
**Arquivo:** [`progress_service.py`](file:///home/felipe/Área de trabalho/Projetos/Foco/app/services/progress_service.py)

### Descrição
A função `apply_cycle_completion` usa `d = cycle.completed_at.date()` para determinar em qual `DailyMinimumProgress`, `DailyIdealProgress` e `WeeklyProgress` incrementar o contador. Se um ciclo foi **iniciado** num dia (ex: 23:50 de segunda) e **completado** no dia seguinte (00:25 de terça), o progresso vai para terça — mas o ciclo pertence à sessão de segunda (a `Session.date == segunda`).

Esse cenário também é ativado pelo BUG-01: ciclos "zumbis" de dias anteriores que ficaram em `status=started` podem ser completados pela API em qualquer momento futuro, incrementando o progresso do dia atual em vez do dia original.

### Causa raiz
```python
# progress_service.py — apply_cycle_completion()
def apply_cycle_completion(cycle) -> dict:
    cfg = cycle.configuration
    d = cycle.completed_at.date()   # ← usa a data de conclusão, não session.date
    
    daily_min = _get_or_create_daily_minimum(d, cfg)
    daily_min.current_count += 1    # ← incrementa no dia errado
```

### Impacto
- Ciclos completados na virada do dia são contabilizados no dia seguinte
- Ciclos "zumbis" (BUG-01) completados via API sobem o progresso do dia corrente

---

## BUG-04 · API não verifica a data do ciclo ao completá-lo

**Severidade:** Média — permite completar ciclos de dias anteriores via requisição direta  
**Arquivo:** [`routes/api.py`](file:///home/felipe/Área de trabalho/Projetos/Foco/app/routes/api.py) · [`engine.py`](file:///home/felipe/Área de trabalho/Projetos/Foco/app/services/engine.py)

### Descrição
O endpoint `POST /api/cycles/<id>/complete` e a função `engine.complete_focus_cycle()` verificam apenas se `cycle.status == "started"`. Não há validação de que o ciclo pertença à sessão do dia atual. Um `FocusCycle` de dias anteriores com `status="started"` (como os do BUG-01) pode ser completado pela API a qualquer momento.

### Causa raiz
```python
# engine.py — complete_focus_cycle()
def complete_focus_cycle(cycle_id: int, title: str | None = None) -> dict:
    cycle = db.session.get(FocusCycle, cycle_id)
    if cycle is None:
        return {"ok": False, "error": "ciclo não encontrado"}

    if cycle.status != "started":   # ← única verificação: status
        return {"ok": True, "already_processed": True, ...}

    # Nenhuma checagem de cycle.session.date == clock.today()
    cycle.completed_at = now()
    cycle.status = "completed"
```

### Impacto
- Combinado com BUG-01 e BUG-03: ciclos de dias passados completados hoje incrementam progresso de hoje

---

## BUG-05 · `Session.date` usa `date_.today()` como default ignorando o clock offset

**Severidade:** Baixa — bug latente, não ativado pelo código atual  
**Arquivo:** [`models.py`](file:///home/felipe/Área de trabalho/Projetos/Foco/app/models.py#L152)

### Descrição
A coluna `Session.date` define `default=date_.today` (Python nativo), que usa o relógio real do sistema operacional, ignorando o offset de debug configurado via `clock.py`. Se uma `Session` for criada **sem especificar `date` explicitamente**, a data ficará errada quando o debug clock estiver deslocado.

```python
# models.py
class Session(db.Model, TimestampMixin):
    date = db.Column(db.Date, nullable=False, default=date_.today, index=True)
    #                                                 ↑ SO time, não clock.today()
```

Na prática, `cycles_service.get_or_create_active_session()` sempre passa `date=today()` explicitamente (linha 39), então o default nunca é usado. Mas código futuro que instanciar `Session()` sem `date=` herdará o bug silenciosamente.

---

## BUG-06 · `water_service.daily_summary` usa configuração atual para exibir meta de água

**Severidade:** Baixa — exibição inconsistente para o dia corrente quando a config muda  
**Arquivo:** [`water_service.py`](file:///home/felipe/Área de trabalho/Projetos/Foco/app/services/water_service.py)

### Descrição
`daily_summary(d)` retorna `goal_ml` e `bottle_ml` sempre da **configuração atual** (`get_current_configuration()`), independente da data consultada. Se a meta de água ou o tamanho da garrafa mudarem no meio do dia, o resumo exibido na Home mostrará a nova meta mesmo para os logs de água registrados antes da mudança.

```python
# water_service.py — daily_summary()
def daily_summary(d: date_) -> dict:
    cfg = get_current_configuration()   # ← sempre config atual
    total_ml = daily_total_ml(d)
    return {
        "goal_ml": cfg.water_goal_ml,   # ← meta pode ter mudado durante o dia
        ...
    }
```

**Contraste:** `daily_service._water()` (usado pelo snapshot histórico) já faz isso corretamente via `get_configuration_at()`. O problema está apenas na rota da Home (`/api/home-state` → `water_service.daily_summary`).

---

## BUG-07 · `todo_service` reconsolida o `Daily` completo a cada operação de to-do

**Severidade:** Baixa — risco de inconsistência em operações compostas  
**Arquivo:** [`todo_service.py`](file:///home/felipe/Área de trabalho/Projetos/Foco/app/services/todo_service.py)

### Descrição
Funções como `create_item`, `toggle_item`, `delete_item` e `update_item_text` chamam `daily_service.consolidate_daily(today(), commit=False)` internamente antes de cada commit. Isso significa que toda operação de to-do **reconsolida o Daily inteiro** — incluindo `cycle_contexts`, `water`, `rewards`. Se essa chamada ocorrer durante uma transação mais ampla (composição de serviços), a reconsolidação pode gravar estado intermediário incorreto ou inconsistente com outros dados ainda pendentes no mesmo flush.

```python
# todo_service.py — create_item()
def create_item(text: str = "") -> TodoItem | None:
    item = TodoItem(...)
    db.session.add(item)
    daily_service.consolidate_daily(today(), commit=False)  # ← recalcula TODO o Daily
    db.session.commit()
```

---

## Resumo

| ID | Descrição curta | Severidade | Confirmação |
|----|-----------------|------------|-------------|
| BUG-01 | `FocusCycles` de dias anteriores ficam em `started` para sempre | **Alta** | Dados reais — 3 ciclos afetados |
| BUG-02 | Snapshots `Daily` consolidados ficam desatualizados após debug | **Alta** | Dados reais — 5 datas afetadas |
| BUG-03 | Progresso atribuído ao `completed_at.date()`, não ao dia da sessão | **Média** | Análise estática |
| BUG-04 | API aceita completar ciclos de dias anteriores sem validação de data | **Média** | Análise estática |
| BUG-05 | `Session.date` default ignora clock offset de debug | **Baixa** | Latente — não ativado atualmente |
| BUG-06 | `water_service.daily_summary` usa config atual para meta histórica | **Baixa** | Análise estática |
| BUG-07 | `todo_service` reconsolida `Daily` completo a cada operação | **Baixa** | Análise estática |
