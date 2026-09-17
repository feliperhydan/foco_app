from datetime import datetime


def utcnow_naive() -> datetime:
    """
    Datetime local da máquina, sem timezone (naive), para uso em
    colunas do banco e timestamps do sistema.

    Usa o horário LOCAL do sistema operacional onde o app está rodando,
    garantindo que ciclos, sessões e registros fiquem atribuídos ao
    dia correto no fuso horário do usuário. Não usa UTC para evitar
    divergências em fusos como UTC-3 (Brasil), onde UTC causaria
    atribuição errada de eventos próximos à meia-noite.
    """
    return datetime.now()
