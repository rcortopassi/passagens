# passagens

Monitor de precos de passagens aereas a partir de Brasilia (BSB), ida e
volta, economica, em quatro abas: Europa (Lyon, Genebra e Lisboa, 2 adultos,
janela fixa de janeiro a marco de 2027), Sao Paulo (Congonhas, 1 adulto),
Rio de Janeiro (Santos Dumont e Galeao, 2 adultos) e Belo Horizonte (Confins,
2 adultos). Sao Paulo e Rio nao tem viagem marcada: janela rolante de 4 meses,
estadias de 2 a 7 noites, para viajar quando estiver barato. Belo Horizonte e
o contrario: data marcada (8 a 10 de janeiro de 2027), um par so, e a decisao
e apenas QUANDO comprar.

Painel: https://rafaelcortopassi.pythonanywhere.com/passagens/

- `passagens/coletor.py` le o Google Flights (RPC GetShoppingResults e
  GetCalendarPicker) e acrescenta ao `historico.json`.
- `passagens/pagina.py` gera o HTML com os dados embutidos e publica.
- O workflow roda de hora em hora; o repositorio e publico porque minutos de
  Actions em repositorio publico nao consomem a cota da conta.
- Os tokens do PythonAnywhere ficam SO nos secrets do Actions e no
  `painel/.env` local; nunca neste repositorio.
