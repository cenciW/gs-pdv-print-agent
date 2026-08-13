# Deixando o agente rodando sozinho

O `gs-pdv-print-agent` precisa estar no ar sempre que o PDV web for usado —
se o computador da loja desligar/reiniciar (falta de luz, atualização do
Windows, etc.), alguém precisa lembrar de abrir o programa de novo antes de
imprimir o primeiro cupom do dia. Este guia mostra como deixar o
computador subir o agente sozinho.

Baixe o executável em [Releases](../../releases/latest) antes de seguir
qualquer seção abaixo — Windows ou Linux, conforme o computador da loja.

## Windows

A forma mais simples, sem instalar nada extra: um atalho na pasta
**Inicializar** do Windows.

1. **Extraia o `.zip` inteiro** (botão direito → "Extrair tudo") pra uma pasta
   fixa, por exemplo `C:\gs-pdv-print-agent\`. O executável **não é um
   arquivo único** — dentro do zip tem `gs-pdv-print-agent.exe` **e** uma
   pasta `_internal\` do lado (runtime do Python + DLLs); sem essa pasta o
   `.exe` não abre nada, nem mostra erro (o cursor pode até "carregar" por um
   instante enquanto o Explorer tenta, mas nenhuma janela chega a aparecer).
   **Nunca copie só o `.exe` sozinho** — sempre a pasta inteira extraída,
   `_internal\` incluída, no mesmo lugar.
2. Na mesma pasta, crie um arquivo `config.json` com o destino da
   impressora (veja o [README](../README.md) para o formato) — ou deixe o
   agente subir sem configurar e ajuste depois pela tela **Configurar
   impressão** do PDV web.
3. Defina a variável de ambiente `AGENT_TOKEN` com a `license_key` do
   tenant (Painel → Config. iFood/Impressão já mostra o token certo) —
   forma mais simples: crie um atalho pro `.exe` e edite as propriedades do
   atalho, campo "Destino", pra:
   ```
   cmd /c "set AGENT_TOKEN=<token-da-loja> && C:\gs-pdv-print-agent\gs-pdv-print-agent.exe"
   ```
4. Pressione `Win + R`, digite `shell:startup` e Enter — abre a pasta
   Inicializar do usuário atual.
5. Copie o atalho criado no passo 3 pra essa pasta.

Pronto — a partir do próximo login do Windows, o agente sobe sozinho
(numa janela de console minimizável, mostrando os logs). Pra testar sem
reiniciar o computador, dê duplo clique no atalho.

> **Alternativa mais robusta (opcional):** registrar como Serviço do
> Windows de verdade (roda mesmo sem ninguém logado) exige uma ferramenta
> como o [NSSM](https://nssm.cc/) — fora do escopo deste guia porque a
> maioria das lojas já deixa o Windows logado o dia inteiro no caixa; avalie
> se o ganho compensa a complexidade extra antes de instalar.

## Linux

Usar `systemd` — já vem em qualquer distribuição usada em PDV (Ubuntu,
Debian, Mint).

1. Copie o binário pra um local fixo:
   ```bash
   sudo mkdir -p /opt/gs-pdv-print-agent
   sudo cp gs-pdv-print-agent /opt/gs-pdv-print-agent/
   sudo chmod +x /opt/gs-pdv-print-agent/gs-pdv-print-agent
   ```
2. Crie `/opt/gs-pdv-print-agent/config.json` com o destino da impressora
   (veja o [README](../README.md)) — ou ajuste depois pela tela do PDV web.
3. Crie a unit `/etc/systemd/system/gs-pdv-print-agent.service`:
   ```ini
   [Unit]
   Description=GS-PDV Print Agent
   After=network.target

   [Service]
   Type=simple
   Environment=AGENT_TOKEN=<token-da-loja>
   WorkingDirectory=/opt/gs-pdv-print-agent
   ExecStart=/opt/gs-pdv-print-agent/gs-pdv-print-agent
   Restart=on-failure
   RestartSec=5
   User=nobody

   [Install]
   WantedBy=multi-user.target
   ```
4. Habilite e suba:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now gs-pdv-print-agent
   ```
5. Conferir que subiu:
   ```bash
   systemctl status gs-pdv-print-agent
   curl http://127.0.0.1:9123/health
   ```

A partir daqui, o agente sobe sozinho em todo boot e reinicia sozinho se
cair (`Restart=on-failure`). Pra ver os logs: `journalctl -u
gs-pdv-print-agent -f`.

## Conexão automática com o dashboard

O dashboard já resolve isso sozinho, sem configuração extra na maioria dos
casos:

- **Endereço do agente**: por padrão `http://127.0.0.1:9123` — funciona
  sem nenhum ajuste sempre que o navegador do operador roda no **mesmo
  computador** que o agente. Se o agente rodar num computador diferente
  na rede da loja, o operador troca o endereço uma única vez em
  **Configurar impressão**; fica salvo no navegador (não precisa repetir
  a cada sessão).
- **Token**: é a `license_key` do tenant — o dashboard já busca e envia
  sozinho a cada impressão, sem o operador precisar digitar nada.

Se o agente estiver rodando mas o dashboard continuar caindo no fallback
do navegador, confira `AGENT_TOKEN` (tem que bater com a license_key do
tenant) e se o navegador está no mesmo computador/rede que o agente.
