# Especificação histórica — Daily, Week e Month

## 1. Princípio central

O **Daily** é a unidade histórica fundamental do sistema. Ele registra o que aconteceu em um determinado dia e o contexto sob o qual aconteceu.

> **Daily registra dados brutos e o contexto necessário para interpretá-los posteriormente. Não realiza interpretações estatísticas.**

`Week` e `Month` serão conjuntos de `Daily`, sobre os quais análises e interpretações poderão ser feitas posteriormente.

```text
DADOS BRUTOS
    │
    ▼
  DAILY
    │
 ┌──┴──┐
 ▼     ▼
WEEK  MONTH
 │     │
 └──┬──┘
    ▼
INTERPRETAÇÃO
    ├── médias
    ├── comparações
    ├── percentuais
    ├── rankings
    └── destaques
```

---

## 2. Protótipo do objeto Daily

```json
{
  "date": "2026-08-13",

  "session_started": true,

  "cycle_contexts": [

    {
      "context_id": 1,

      "configuration": {
        "focus_minutes": 35,
        "short_break_minutes": 5,
        "long_break_minutes": 15,

        "cycles_per_session": 4,

        "daily_minimum_goal": 6,
        "daily_ideal_goal": 8,
        "weekly_goal": 40
      },

      "focus": {
        "cycles_completed": 8,
        "minutes_completed": 280,

        "titles": [
          {
            "text": "Estudar programação",
            "cycle_count": 1
          },
          {
            "text": "Revisar documentação",
            "cycle_count": 1
          },
          {
            "text": "Implementar Daily",
            "cycle_count": 2
          }
        ]
      },

      "rest_short": {
        "cycles_completed": 6,
        "minutes_completed": 30
      },

      "rest_long": {
        "cycles_completed": 2,
        "minutes_completed": 30
      },

      "extraordinary": {
        "cycles": 2,
        "minutes": 70
      }
    },

    {
      "context_id": 2,

      "configuration": {
        "focus_minutes": 45,
        "short_break_minutes": 5,
        "long_break_minutes": 15,

        "cycles_per_session": 4,

        "daily_minimum_goal": 6,
        "daily_ideal_goal": 9,
        "weekly_goal": 40
      },

      "focus": {
        "cycles_completed": 3,
        "minutes_completed": 135,

        "titles": [
          {
            "text": "Refatorar estatísticas",
            "cycle_count": 1
          },
          {
            "text": null,
            "cycle_count": 1
          }
        ]
      },

      "rest_short": {
        "cycles_completed": 2,
        "minutes_completed": 10
      },

      "rest_long": {
        "cycles_completed": 1,
        "minutes_completed": 15
      },

      "extraordinary": {
        "cycles": 0,
        "minutes": 0
      }
    }
  ],

  "water": {
    "contexts": [
      {
        "context_id": 1,

        "bottle_capacity_ml": 750,
        "daily_goal_ml": 3000,

        "bottles_consumed": 3,
        "water_consumed_ml": 2250
      }
    ]
  },

  "todo": {
    "items_total": 10,
    "items_completed": 8
  },

  "rewards": {

    "daily_minimum": {
      "title": "Trabalhar",
      "cycles_computed": 6,
      "goal_completed": true
    },

    "daily_ideal": {
      "title": "Alta produtividade",
      "cycles_computed": 9,
      "goal_completed": true
    },

    "weekly": {
      "title": "Semana forte",
      "cycles_computed": 40,
      "goal_completed": true
    },

    "absolute": {
      "title": "Projeto MP3",

      "start": {
        "current_cycles": 734,
        "goal_cycles": 1000
      },

      "end": {
        "current_cycles": 743,
        "goal_cycles": 1000
      },

      "cycles_computed": 9,
      "goal_completed": false
    }
  }
}
```

---

## 3. Títulos escritos pelo usuário ao concluir ciclos

Ao terminar um ciclo de foco, o usuário pode informar **o que foi feito naquele ciclo**. Esse texto deve ser preservado como dado bruto no Daily.

Exemplo:

```json
{
  "text": "Estudar programação",
  "cycle_count": 1
}
```

Se o mesmo título for utilizado em mais de um ciclo, pode ser representado de forma agregada:

```json
{
  "text": "Implementar Daily",
  "cycle_count": 2
}
```

### Regras

A quantidade de títulos nunca pode ser maior que a quantidade de ciclos de foco completos:

```text
quantidade_de_titulos <= focus.cycles_completed
```

Pode ser menor.

Exemplo válido:

```text
8 ciclos completos
5 títulos registrados
```

Exemplo inválido:

```text
8 ciclos completos
9 títulos registrados
```

O usuário pode concluir um ciclo sem informar nada. Nesse caso:

```json
{
  "text": null,
  "cycle_count": 1
}
```

`null` significa que houve ciclo concluído, mas não houve descrição fornecida.

O sistema não deve gerar títulos automaticamente, criar atividades inexistentes ou interpretar semanticamente o texto informado.

---

## 4. Contextos de ciclo

`cycle_contexts` é uma lista porque a configuração pode mudar durante o dia.

Exemplo:

```text
08:00
Contexto A
35 min de foco

12:00
Configuração alterada

Contexto B
45 min de foco
```

O Daily preserva:

```text
Daily
├── Contexto 1
│   ├── configuração
│   └── resultados produzidos sob ela
│
└── Contexto 2
    ├── configuração
    └── resultados produzidos sob ela
```

Os dados de um contexto nunca devem ser misturados com os dados de outro.

Cada contexto contém o snapshot dos parâmetros da configuração:

- `focus_minutes`
- `short_break_minutes`
- `long_break_minutes`
- `cycles_per_session`
- `daily_minimum_goal`
- `daily_ideal_goal`
- `weekly_goal`

Esses valores são **contexto**, não resultados.

---

## 5. Dados de foco

Para cada contexto:

```json
"focus": {
  "cycles_completed": 8,
  "minutes_completed": 280,
  "titles": [...]
}
```

São dados brutos:

- ciclos completos;
- minutos correspondentes;
- títulos informados pelo usuário.

Não pertencem ao Daily:

- percentual de produtividade;
- comparação com meta;
- média;
- eficiência;
- tempo líquido;
- tempo bruto;
- crescimento.

Essas interpretações pertencem à camada posterior.

---

## 6. Descansos

Descanso curto:

```json
"rest_short": {
  "cycles_completed": 6,
  "minutes_completed": 30
}
```

Descanso longo:

```json
"rest_long": {
  "cycles_completed": 2,
  "minutes_completed": 30
}
```

O Daily registra separadamente:

- ciclos de foco;
- ciclos de descanso curto;
- ciclos de descanso longo;
- minutos de cada um;
- ciclos extraordinários;
- minutos extraordinários.

Não calcula tempo líquido, tempo bruto, proporção foco/descanso ou eficiência.

---

## 7. Extraordinário

```json
"extraordinary": {
  "cycles": 2,
  "minutes": 70
}
```

O ciclo que completa exatamente a meta ideal não é extraordinário. O extraordinário começa somente depois que a meta ideal já estava concluída.

---

## 8. Água

A água segue a mesma filosofia de snapshot:

```json
"water": {
  "contexts": [
    {
      "context_id": 1,
      "bottle_capacity_ml": 750,
      "daily_goal_ml": 3000,
      "bottles_consumed": 3,
      "water_consumed_ml": 2250
    }
  ]
}
```

O contexto contém:

- capacidade da garrafa;
- meta diária.

Os resultados contêm:

- quantidade de garrafas;
- ml consumidos.

Se a configuração mudar durante o dia, cria-se outro contexto. Dados anteriores permanecem ligados ao contexto anterior.

---

## 9. To-do

O Daily guarda somente dados brutos:

```json
"todo": {
  "items_total": 10,
  "items_completed": 8
}
```

Não guardar `80%`. O percentual será calculado posteriormente.

---

## 10. Recompensas

O Daily registra o estado das recompensas que estava vigente e que se concretizou no período.

Para cada entidade:

- mínimo;
- ideal;
- semanal;
- absoluto;

registrar:

- título;
- quantidade de ciclos computados;
- se a meta foi concluída.

Exemplo:

```json
"daily_minimum": {
  "title": "Trabalhar",
  "cycles_computed": 6,
  "goal_completed": true
}
```

O título é um snapshot histórico. Alterações futuras não devem reescrever o Daily antigo.

---

## 11. Objetivo absoluto

O absoluto é diferente porque possui progressão contínua.

Registrar estado inicial e final:

```json
"absolute": {
  "title": "Projeto MP3",

  "start": {
    "current_cycles": 734,
    "goal_cycles": 1000
  },

  "end": {
    "current_cycles": 743,
    "goal_cycles": 1000
  },

  "cycles_computed": 9,
  "goal_completed": false
}
```

O Daily deve conseguir responder diretamente:

- onde o objetivo estava no começo;
- onde terminou;
- quantos ciclos foram computados;
- qual era a meta;
- qual título estava associado;
- se foi concluído naquele dia.

Não depender de outra entidade para reconstruir esse estado histórico.

---

## 12. Daily autocontido

Um Daily deve conseguir explicar historicamente o que aconteceu naquele dia sem depender da configuração atual do sistema.

Referências técnicas podem existir, mas não devem ser a única fonte necessária para reconstruir o passado.

Isso vale especialmente para:

- configuração dos ciclos;
- configuração da água;
- títulos de recompensas;
- estado do absoluto;
- títulos escritos pelo usuário.

---

## 13. Daily não interpreta

Não pertencem ao Daily:

- tempo líquido;
- tempo bruto;
- percentuais;
- médias;
- crescimento;
- queda;
- produtividade;
- eficiência;
- ranking;
- consistência;
- melhor/pior dia;
- comparação com semana anterior;
- comparação com mês anterior.

O Daily guarda os ingredientes para que essas análises sejam feitas depois.

---

## 14. Week

Week será um conjunto de Daily pertencentes a uma semana:

```text
Week
├── Daily 01
├── Daily 02
├── Daily 03
├── Daily 04
├── Daily 05
├── Daily 06
└── Daily 07
```

Poderá posteriormente calcular:

- ciclos totais;
- minutos totais;
- foco;
- descanso;
- tempo líquido;
- tempo bruto;
- água;
- médias diárias;
- média de ciclos;
- média de minutos;
- percentual de To-do;
- recompensas;
- evolução do absoluto;
- comparação com semana anterior;
- configurações utilizadas;
- distribuição das atividades.

Os Daily não devem ser destruídos ou reescritos por essas agregações.

---

## 15. Month

Month seguirá a mesma filosofia:

```text
Month
├── Daily 01
├── Daily 02
├── Daily 03
├── ...
└── Daily 31
```

Poderá produzir:

- totais mensais;
- médias diárias;
- comparação com mês anterior;
- comparação semana a semana;
- consistência;
- evolução de ciclos;
- evolução de minutos;
- hidratação;
- To-do;
- recompensas;
- objetivo absoluto;
- destaques/fanfacts.

Exemplo futuro:

> atividade mais recorrente do mês

ou:

> dia com maior quantidade de ciclos.

Esses são dados derivados, não dados primários.

---

## 16. Regra de ouro

```text
DAILY
= "O que aconteceu?"

WEEK
= "O que aconteceu nesta semana?"

MONTH
= "O que aconteceu neste mês?"

INTERPRETAÇÃO
= "O que esses acontecimentos significam?"
```

---

## 17. Histórico e imutabilidade

Dados históricos não devem ser recalculados usando a configuração atual.

Se uma configuração era:

```text
35 minutos
```

e depois mudou para:

```text
45 minutos
```

os dados antigos continuam representando 35 minutos.

O mesmo vale para:

- pausas;
- metas;
- garrafas;
- metas de água;
- títulos de recompensa;
- objetivo absoluto;
- títulos escritos pelo usuário.

Alterações futuras não devem reescrever o passado.

---

## 18. Contexto múltiplo

Sempre que uma configuração relevante mudar durante o dia:

```text
Daily
│
├── Contexto 1
│   └── dados produzidos antes da mudança
│
└── Contexto 2
    └── dados produzidos depois da mudança
```

Não misturar dependências.

---

## 19. Checklist de implementação

- [ ] Daily possui uma data.
- [ ] Daily registra se uma sessão foi iniciada.
- [ ] Configurações de ciclo são snapshots históricos.
- [ ] Configurações diferentes no mesmo dia criam contextos separados.
- [ ] Dados produzidos sob contextos diferentes nunca são misturados.
- [ ] Ciclos de foco são registrados em quantidade e minutos.
- [ ] Descansos curtos são registrados em quantidade e minutos.
- [ ] Descansos longos são registrados em quantidade e minutos.
- [ ] Extraordinários são registrados em quantidade e minutos.
- [ ] Títulos informados ao concluir ciclos são preservados.
- [ ] Um título pode ser `null`.
- [ ] A quantidade de títulos nunca pode exceder a quantidade de ciclos de foco completos.
- [ ] To-do registra quantidade total e quantidade concluída.
- [ ] Água registra contexto da garrafa e da meta.
- [ ] Água registra quantidade de garrafas e ml consumidos.
- [ ] Recompensas preservam o título vigente no momento em que se concretizam.
- [ ] Recompensas preservam quantidade de ciclos computados.
- [ ] Recompensas preservam se a meta foi concluída.
- [ ] Absoluto registra estado inicial e final.
- [ ] Absoluto registra a progressão computada no Daily.
- [ ] Daily não calcula percentuais.
- [ ] Daily não calcula médias.
- [ ] Daily não compara períodos.
- [ ] Daily não interpreta produtividade.
- [ ] Week é formado por Daily.
- [ ] Month é formado por Daily.
- [ ] Week e Month podem interpretar/agregar os dados sem alterar o histórico dos Daily.
- [ ] O passado nunca deve depender da configuração atual para ser reconstruído.
