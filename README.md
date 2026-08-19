# gs-pdv-print-agent

Serviço local (roda na loja, na mesma rede da impressora) que recebe o texto
do cupom do `gs-menu-dashboard` (PDV web) e imprime numa térmica ESC/POS —
rede (porta 9100), Windows (`win32print`) ou Linux/CUPS.

Existe porque impressoras térmicas de rede não falam com `window.print()`; só
bytes ESC/POS crus por socket. Portado byte a byte do GS-PDV desktop (ver
`app/escpos.py`) — não é uma reimplementação, é o mesmo payload já depurado.

## Por que o dashboard não fala direto com a impressora

O navegador não tem acesso a sockets TCP crus nem a impressoras do SO. Este
agente é a ponte: um serviço HTTP local que o JavaScript do dashboard pode
chamar (`fetch("http://127.0.0.1:9123/print")`), e que por sua vez fala
ESC/POS de verdade. Se o agente não estiver rodando, o dashboard cai
automaticamente para `window.print()` (fallback do navegador) — a venda
nunca fica bloqueada esperando a impressora.

## Rodando localmente (dev)

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

AGENT_TOKEN=<pdv_license_key do tenant, ver Configurações no dashboard> \
PRINTER_DEST=192.168.1.50 \
python main.py
```

- `AGENT_TOKEN` — segredo que o dashboard precisa mandar em
  `Authorization: Bearer <token>`. **Reaproveita o `pdv_license_key` do
  tenant** (Configurações → GS-PDV, já existe pra outras integrações) — não
  é preciso inventar/distribuir um segredo novo. Sem token configurado, todo
  `POST /print` é recusado (falha fechada).
- `PRINTER_DEST` — `192.168.1.50` ou `192.168.1.50:9100` (rede, porta 9100
  se omitida) ou o nome da impressora no SO (Windows/CUPS).
- `ALLOWED_ORIGINS` — origens do navegador aceitas (`Origin` header),
  separadas por vírgula. Default `http://localhost:3001`; em produção,
  algo como `https://painel.gs-menu.com.br`.
- `ALLOW_PRIVATE_NETWORK_ORIGINS` — aceitar **também** qualquer endereço de
  rede local (`10.x`, `192.168.x`, `172.16–31.x`, `localhost`, `*.local`), em
  qualquer porta. **Ligado por padrão desde a v0.4.0**: o painel aberto no
  celular do salão chega como `http://192.168.x.x:3001`, endereço que muda de
  loja para loja e não cabe numa lista fixa. `0`/`false` desliga.
- `AGENT_PORT` — porta HTTP local do agente. Default `9123`.

Alternativa a variáveis de ambiente: um `config.json` ao lado do executável
(`{"printer_dest": "...", "token": "...", "allowed_origins": [...], "port": 9123}`)
— env var sempre vence se as duas existirem (só quando ela **existe de
verdade**: uma env var presente mas vazia, tipo `AGENT_TOKEN=`, cai pro
`config.json` do mesmo jeito que se estivesse ausente).

**Mais simples que os dois:** rode o executável direto (duplo clique ou
`./gs-pdv-print-agent` num terminal) sem nenhum token configurado — se tiver
um console de verdade ali (não é o caso de rodar como serviço/systemd sem
terminal), o agente pergunta o token na hora e grava sozinho no
`config.json`, sem precisar editar arquivo nenhum. Só pergunta uma vez por
computador.

## Endpoints

- `GET /health` — sem auth (é só o probe de liveness que o dashboard usa
  antes de decidir entre agente e fallback, timeout ~1.5s). Retorna
  `{"status": "ok", "printer_configured": bool}`.
- `POST /print` — `{"text": "<cupom monoespaçado>"}`, exige
  `Authorization: Bearer <token>` e `Origin` autorizada. O texto já vem
  pronto do `gs-menu-server` (`GET /api/restaurant/sales/{id}/receipt`) —
  o agente só embrulha em ESC/POS e envia, nunca formata nada (garante que a
  prévia em tela e o cupom impresso saiam idênticos).
- `GET /printers` — impressoras instaladas neste computador (spooler do
  Windows / CUPS), para o painel oferecer a escolha em vez de exigir o nome
  digitado à mão. **Exige token**, diferente de `/health`: nome de impressora
  é informação da máquina da loja. Lista vazia significa "não consegui
  descobrir" (sem spooler, CUPS fora do ar), nunca "não há impressora" — o
  painel cai no campo de texto livre, que é também o caminho da impressora de
  rede, que não aparece em spooler nenhum.

## Interface (janela + bandeja)

Desde a **v0.3.0** o agente é um **aplicativo desktop**: duplo-clique no
executável e a janela de configuração abre. Toda a configuração está nela —
não é preciso abrir o painel web para instalar o agente.

A janela tem três blocos:

- **Impressora** — escolha entre *instalada neste computador* (lista do
  spooler/CUPS, com busca que filtra enquanto se digita) e *impressora de rede
  (IP)*; largura do papel (80 mm / 58 mm) e **Testar impressão**, que imprime
  na largura da tela mesmo antes de salvar (calibrar é imprimir, olhar o papel
  e ajustar).
- **Conexão com o painel** — token do agente.
- **Sistema** — iniciar com o computador, abrir a pasta de configuração, ver o
  log, reiniciar.

A barra de status embaixo responde "dá para imprimir agora?" — e avisa em
vermelho quando **não** dá (sem token, o agente recusa tudo).

### A bandeja é acessório, não a interface

O ícone na área de notificação (no Windows, atrás da setinha "mostrar ícones
ocultos") mostra o estado e dá atalho para abrir a configuração, testar,
alternar o início automático, reiniciar e sair.

**Ela nunca é dona da thread principal** — a janela é. Isso não é detalhe de
estilo: era a arquitetura invertida que quebrou a v0.2.0 em duas frentes.

| Sistema | O que acontecia na v0.2.0 |
|---|---|
| **Windows** | O `pystray` despacha o callback do menu de dentro da bomba de mensagens (`_win32.py:224`). Abrir a janela ali **congelava a bandeja** enquanto a janela vivesse. |
| **Linux/X11** | Pior e silencioso: `pystray/_xorg.py` declara `HAS_MENU = False` e `_update_menu` é `pass` ("Menus are not supported on X"). O menu inteiro era **descartado sem aviso** — o ícone aparecia e não fazia nada. |

Agora todo item de menu apenas **enfileira** a ação para o laço da janela
(`AgentWindow.agendar`) e retorna em microssegundos. O código também
**pergunta** se o sistema desenha menu (`tray.suporta_menu()`) em vez de
assumir: onde não desenha, a janela não se esconde na bandeja — esconder
deixaria a configuração inalcançável.

### Uma configuração, várias portas

Janela, bandeja e rotas HTTP chamam o **mesmo** `app/agent_actions.py`. Salvar
pelo painel web avisa a janela aberta (padrão Observador), então as duas portas
nunca divergem sobre qual impressora está configurada.

**A interface é opcional.** Sem `pystray`/`Pillow`, sem Tk, sem ambiente
gráfico ou com falha no arranque da interface: o agente loga e **segue
imprimindo** como serviço. Quem manda é o serviço, não a tela.

### Modo serviço (`--headless`)

```bash
python main.py --headless      # ou GS_AGENT_GUI=0
```

Sem janela e sem bandeja — é o que systemd/serviço usa. O prompt de token
continua acontecendo no console quando há um terminal de verdade.

### Log

O agente escreve em `gs-pdv-print-agent.log`, **ao lado do `config.json`**
(rotação a cada 1 MB, 3 arquivos). Não é conforto: o build do Windows é
*windowed*, sem console — sem o arquivo, diagnosticar problema em máquina de
cliente vira adivinhação. Pedir "manda o log" só funciona se ele estiver onde
a pessoa já sabe procurar.

## Segurança

Duas camadas, falha fechada nas duas:
1. **Token** — comparado com `secrets.compare_digest` (nunca `==`), mesma
   regra do resto do monorepo.
2. **Origin** — só origem da allowlist (ou da **rede local**, ver
   `ALLOW_PRIVATE_NETWORK_ORIGINS`) pode chamar `/print`, mesmo com token
   certo. Endereço de fora da LAN continua barrado — e registrado, para a
   janela poder oferecer autorizar.

Isto é uma simplificação deliberada do "token efêmero por sessão do
operador" cogitado no planejamento original: um segredo estático
(`pdv_license_key`) + Origin restrita + bind só em LAN/localhost já cobre o
requisito real ("nunca HTTP aberto sem auth na LAN") sem precisar construir
um fluxo de emissão/expiração de token novo. Revisitar se o agente algum dia
precisar ser alcançável fora de uma LAN confiável.

## Testes

```bash
source venv/bin/activate
python -m pytest tests/ -v
```

`tests/test_printer_client.py` sobe um servidor TCP de verdade em
`127.0.0.1` (não mocka `socket.socket`) — verifica o caminho de impressora
de rede, que é o padrão já instalado no parque de clientes.

## Empacotamento (PyInstaller)

Distribuído como executável, mesmo padrão do GS-PDV desktop
(`build_executables.sh`/`GS-PDV.spec`). Duas opções merecem atenção:

- **`console=False` (`--windowed`)** — um console preto atrás da janela é
  fechado por engano, derrubando a impressão da loja. Só é seguro porque o log
  vai para arquivo (ver acima).
- **`--collect-all tkinter`** — `--hidden-import tkinter` traz o *módulo*, mas
  a janela precisa dos *dados* do Tcl/Tk. Com o import preguiçoso, o hook pode
  não disparar: o build passa, o `.exe` sobe e a janela falha **só na máquina
  do cliente**.

> ⚠️ O CI **não usa** o `.spec` — `build_and_release.yml` repete as opções em
> linha de comando. Mudou uma, mude nos dois lugares.

```bash
source venv/bin/activate
pip install pyinstaller
./build_agent.sh          # gera dist/gs-pdv-print-agent (Linux)
```

O build Windows (`.exe`) é feito pelo GitHub Actions
(`.github/workflows/build_and_release.yml`) a cada tag `vX.Y.Z` — publica
os dois binários (Windows + Linux) numa Release.

> **`_config_path()` (`app/config.py`) resolve `config.json` relativo ao
> diretório do *executável*, não ao CWD, quando `sys.frozen` — bug real
> encontrado ao empacotar: `python main.py` sempre roda com CWD = pasta do
> projeto, mas um `.exe` invocado por atalho/serviço pode ter qualquer CWD.
> Sem esse cuidado, o binário empacotado ora não achava o `config.json` que
> o técnico editou, ora gravava um novo em outro lugar silenciosamente a
> cada restart.** Nunca embutir `AGENT_TOKEN`/`PRINTER_DEST` no binário —
> sempre env var ou `config.json` ao lado do executável, editado na
> instalação de cada loja.

⚠️ **Pendência real, não testada nesta sessão:** o binário empacotado só
foi confirmado contra uma impressora TCP fake — falta testar contra
impressora térmica física de verdade (mesma pendência que já existia pro
build via `python main.py`).

Deixando o agente rodando sozinho no boot da máquina da loja (Windows/
Linux) e conectando automaticamente com o dashboard: ver
[`docs/AUTOSTART.md`](docs/AUTOSTART.md).
