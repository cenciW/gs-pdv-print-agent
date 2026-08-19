# Deixando o agente rodando sozinho

O `gs-pdv-print-agent` precisa estar no ar sempre que o PDV web for usado —
se o computador da loja desligar/reiniciar (falta de luz, atualização do
Windows, etc.), alguém precisa lembrar de abrir o programa de novo antes de
imprimir o primeiro cupom do dia. Este guia mostra como deixar o
computador subir o agente sozinho.

> **O caminho mais curto é dentro do próprio agente.** Abra o programa e marque
> **"Iniciar junto com o computador"** (na janela, seção *Sistema*, ou pelo
> menu do ícone da bandeja). Pronto — ele se registra sozinho, e desmarcar
> remove.
>
> **Na v0.4.0 isso mudou de mecanismo no Windows:** era um atalho na pasta
> Inicializar, que depende do Explorer executá-lo e pode ser desligado por fora
> em *Gerenciador de Tarefas > Inicializar* — foi por isso que houve caso de
> "abre normal, mas não sobe com o Windows". Agora o registro é na chave `Run`
> do Windows, executada pelo próprio logon. O agente ainda **conserta sozinho**
> o caminho se você mover o programa de pasta, e **avisa na janela** quando é o
> Windows que está com a inicialização desativada.
>
> As seções abaixo continuam valendo para quem prefere fazer à mão, ou para
> quem precisa de um **serviço de verdade** no Linux (systemd roda mesmo sem
> ninguém logado; o registro da janela depende da sessão do usuário).

Baixe o executável em [Releases](../../releases/latest) antes de seguir
qualquer seção abaixo — Windows ou Linux, conforme o computador da loja.

## Windows

> ## ⚠ Passo 0 — desbloqueie o `.zip` ANTES de extrair
>
> Botão direito no arquivo baixado → **Propriedades** → marque
> **Desbloquear** → **OK**. **Só então** extraia.
>
> Sem isso o Windows marca o executável como "baixado da internet" e:
> **o duplo clique não abre nada** (só abre pelo prompt de comando, porque quem
> confere a marca é o Explorer), e ele **pergunta se você confia no programa a
> cada início** — o que anula a inicialização automática, já que o agente fica
> esperando alguém clicar.
>
> Confirmado em uso real (2026-08-19): desbloqueando o zip antes de extrair,
> tudo funciona — duplo clique, inicialização junto com o Windows, impressão
> pelo painel. **É um passo, e evita os três problemas.**
>
> Já extraiu sem desbloquear? Abra o agente pelo prompt
> (`.\gs-pdv-print-agent.exe`) e use o botão **"Não pedir mais"** na seção
> *Sistema* da janela.

1. **Extraia o `.zip`** pra uma pasta fixa, por exemplo
   `C:\gs-pdv-print-agent\`. Desde a **v0.4.0** o programa é **um arquivo
   só** (`gs-pdv-print-agent.exe`) — pode copiar e mover à vontade, desde que
   o `config.json` ande junto, na mesma pasta.

   > Nas versões até a v0.3.2 o zip trazia o `.exe` **mais** uma pasta
   > `_internal\` ao lado, e copiar só o `.exe` fazia o programa não abrir
   > nada — nem erro. Se você tem uma instalação antiga assim, apague a pasta
   > inteira e extraia a nova por cima; leve só o `config.json` do lugar velho.
2. Configure o token (obrigatório — sem ele o agente recusa toda impressão).
   Três jeitos, do mais simples ao mais manual:
   - **Baixe o `config.json` pronto** na tela **Impressão** do painel (botão
     "Baixar config.json pronto") — já vem com token e impressora
     preenchidos, só arrastar pra pasta do passo 1.
   - **Ou abra `gs-pdv-print-agent.exe` uma vez** (duplo clique): se ainda
     não tiver token configurado, ele **abre uma janelinha pedindo o token** —
     cole o valor (copie da tela **Impressão** do painel) e aperte Enter. Só
     pergunta uma vez; grava sozinho no `config.json`. (Rodando pelo terminal,
     com `--headless` ou via `python main.py`, ele pergunta no console em vez
     de abrir janela.)
   - Ou defina manualmente: `AGENT_TOKEN` como variável de ambiente, ou
     edite `config.json` à mão (veja o [README](../README.md) para o
     formato).
3. Abra o programa e marque **"Iniciar junto com o computador"** na seção
   *Sistema* da janela. É isso — não precisa criar atalho nem mexer em pasta
   de inicialização.

Pronto: a partir do próximo login do Windows, o agente sobe sozinho. Pra testar
sem reiniciar, feche e abra o programa.

### "Só abre pelo prompt de comando, duplo clique não faz nada"

Mesma causa da seção seguinte, e vale destacar porque o sintoma é diferente:
**quem confere a marca de "arquivo baixado da internet" é o Explorer**, não o
`cmd`. Por isso o mesmo executável abre digitando `.\gs-pdv-print-agent.exe` e
parece morto no duplo clique.

**A forma de nunca passar por isso: desbloqueie o `.zip` ANTES de extrair** —
botão direito no arquivo baixado → Propriedades → marque **Desbloquear** → OK.
Os arquivos extraídos saem limpos.

Se já extraiu, abra o agente pelo `cmd` uma vez e use o botão **"Não pedir
mais"** (seção seguinte) — o duplo clique volta a funcionar.

### "Ele sobe sozinho, mas pede uma permissão para executar"

Isso é o Windows, não o agente: arquivo **baixado da internet** chega marcado, e
enquanto a marca existir ele pergunta se você confia no programa **toda vez**.
Num computador de loja isso anula a inicialização automática — o agente fica
esperando alguém clicar, e o primeiro cupom do dia não sai.

O agente detecta e oferece resolver: na janela, seção *Sistema*, aparece
**"O Windows pede confirmação toda vez que o agente abre"** com o botão
**"Não pedir mais"**. Um clique e acabou.

À mão dá no mesmo: botão direito no `gs-pdv-print-agent.exe` → **Propriedades**
→ marque **Desbloquear** → OK.

> A causa de fundo é o executável não ser assinado digitalmente — assinar tem
> custo anual e ficou para depois. Desbloquear resolve para a cópia instalada;
> ao trocar de versão, a marca volta com o arquivo novo.

> **Prefere fazer à mão?** `Win + R` → `shell:startup` abre a pasta
> Inicializar do usuário; um atalho para o `.exe` ali dentro também funciona.
> Só não use os dois caminhos ao mesmo tempo: o agente subiria duas vezes e a
> segunda morreria com a porta ocupada (ligar a opção no programa **apaga** um
> atalho antigo dessa pasta, justamente para evitar isso).

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
2. Configure o token e a impressora em `/opt/gs-pdv-print-agent/config.json`
   — o jeito mais simples é baixar o arquivo já pronto na tela
   **Impressão** do painel (botão "Baixar config.json pronto") e colocar
   nesse caminho; alternativa manual: rode `./gs-pdv-print-agent` uma vez
   direto no terminal (fora do systemd) — sem token configurado, ele
   pergunta e grava sozinho. **Rodando como serviço `systemd` (sem terminal
   de verdade anexado) o agente nunca pergunta nada** — por isso o token
   precisa já estar no `config.json` (ou na `Environment=` da unit abaixo)
   antes de habilitar o serviço.
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

## Marquei "iniciar com o computador" e mesmo assim não subiu

O menu não guarda um "sim/não" em lugar nenhum: ele responde **olhando o
arquivo de inicialização**. Se a opção aparece ligada, o arquivo existe. O
problema, então, está entre existir e ser executado.

Confira, depois de reiniciar, se o arquivo continua lá:

- Windows:
  `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\gs-pdv-print-agent.cmd`
- Linux: `~/.config/autostart/gs-pdv-print-agent.desktop`

**Se o arquivo sumiu**, alguém o removeu — antivírus (o Defender já apagou o
instalador uma vez), limpeza de disco ou outro perfil de usuário.

**Se o arquivo continua lá e mesmo assim nada sobe**, abra-o num editor: ele
guarda o caminho absoluto de onde o agente estava **no momento em que a opção
foi ligada**. Se o programa foi movido de pasta depois disso — o caso mais
comum é ligar a opção rodando de dentro da pasta de Downloads e depois mover
para `Arquivos de Programas` —, o comando aponta para o vazio e falha em
silêncio. Solução: desligar e religar a opção com o agente já no lugar
definitivo.

**No Linux**, o `.desktop` de `~/.config/autostart` só roda quando **aquele
usuário faz login na sessão gráfica**. Reiniciar e parar na tela de login não
sobe nada. Se a loja precisa do agente no ar sem ninguém logado, é o caso de
usar a unit do systemd descrita acima, não o atalho de sessão.
