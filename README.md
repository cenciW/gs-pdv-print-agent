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
- `AGENT_PORT` — porta HTTP local do agente. Default `9123`.

Alternativa a variáveis de ambiente: um `config.json` ao lado do executável
(`{"printer_dest": "...", "token": "...", "allowed_origins": [...], "port": 9123}`)
— env var sempre vence se as duas existirem.

## Endpoints

- `GET /health` — sem auth (é só o probe de liveness que o dashboard usa
  antes de decidir entre agente e fallback, timeout ~1.5s). Retorna
  `{"status": "ok", "printer_configured": bool}`.
- `POST /print` — `{"text": "<cupom monoespaçado>"}`, exige
  `Authorization: Bearer <token>` e `Origin` autorizada. O texto já vem
  pronto do `gs-menu-server` (`GET /api/restaurant/sales/{id}/receipt`) —
  o agente só embrulha em ESC/POS e envia, nunca formata nada (garante que a
  prévia em tela e o cupom impresso saiam idênticos).

## Segurança

Duas camadas, falha fechada nas duas:
1. **Token** — comparado com `secrets.compare_digest` (nunca `==`), mesma
   regra do resto do monorepo.
2. **Origin** — só as origens da allowlist podem chamar `/print`, mesmo com
   token certo. Uma LAN de loja não é rede confiável por padrão.

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

Distribuído como executável único, mesmo padrão do GS-PDV desktop
(`build_executables.sh`/`GS-PDV.spec`), com uma diferença: `console=True`
(é um serviço headless, não um app com janela — o técnico precisa ver os
logs ao rodar manualmente) e sem ícone (não há taskbar/dock pra um
processo sem janela).

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
