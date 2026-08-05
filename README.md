# passagens

Monitor de precos de passagens aereas Brasilia (BSB) para Lyon, Genebra e
Lisboa; ida e volta, 2 adultos, economica; partidas de janeiro a marco de 2027.

Painel: https://rafaelcortopassi.pythonanywhere.com/passagens/

- `passagens/coletor.py` le o Google Flights (RPC GetShoppingResults e
  GetCalendarPicker) e acrescenta ao `historico.json`.
- `passagens/pagina.py` gera o HTML com os dados embutidos e publica.
- O workflow roda de hora em hora; o repositorio e publico porque minutos de
  Actions em repositorio publico nao consomem a cota da conta.
- Os tokens do PythonAnywhere ficam SO nos secrets do Actions e no
  `painel/.env` local; nunca neste repositorio.
