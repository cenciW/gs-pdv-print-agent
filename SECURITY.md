# Política de segurança

O `gs-pdv-print-agent` roda **dentro da loja**, na mesma máquina ou na mesma
rede da impressora térmica, e recebe do navegador o texto do cupom já pronto.
Ele não guarda dados de venda, não fala com a internet e não tem banco.

## Como reportar uma falha

Use o **Security Advisory privado** do GitHub:

> **Security** → **Report a vulnerability**
> (<https://github.com/cenciW/gs-pdv-print-agent/security/advisories/new>)

**Não abra issue pública** para falha de segurança. Uma issue é visível para
qualquer pessoa no instante em que é criada, e este agente roda em lojas reais
— o aviso chegaria antes da correção.

Resposta em até **7 dias corridos**. Se não houver retorno nesse prazo, cobre
pelo mesmo canal antes de divulgar.

Ao reportar, ajuda muito incluir: versão do agente (aparece na janela e no
`gs-pdv-print-agent.log`), sistema operacional, e o passo a passo para
reproduzir.

## Versões suportadas

| Versão | Situação |
|---|---|
| última release (`v0.4.0`) | recebe correção |
| anteriores | atualize antes de reportar |

Só a última release recebe correção. O agente é pequeno e a atualização é
trocar o executável.

## Modelo de ameaça

O agente escuta em `0.0.0.0:9123`. O adversário relevante é **quem já está na
rede local da loja** — um aparelho no Wi-Fi de visitantes, por exemplo. Não é
um serviço exposto à internet, e **não deve ser publicado com redirecionamento
de porta no roteador**: se ele estiver alcançável de fora, isso é um problema
de instalação, não do programa.

O pior resultado de um abuso é **imprimir papel indevido** na loja. Não há
dado de cliente nem de venda armazenado no agente.

## Defesas deliberadas

Estas escolhas são intencionais — não precisa reportá-las como falha:

- **Token obrigatório em tudo que não seja `/health`**, e a falha é fechada:
  sem token configurado, `/print` responde **503 e não imprime nada**, em vez
  de aceitar por omissão.
- **Comparação de token com `secrets.compare_digest`**, nunca `==`, para não
  vazar o token pelo tempo de resposta.
- **`Origin` conferida**, junto com o token: vale a lista `allowed_origins` e,
  por padrão, **qualquer endereço de rede local** (`10.x`, `192.168.x`,
  `172.16–31.x`, `localhost`, `*.local`). Isso é deliberado desde a v0.4.0: o
  painel aberto no celular do salão chega como `http://192.168.x.x:3001`,
  endereço que muda de loja para loja e não cabe numa lista fixa — e sem isso o
  agente ficava inalcançável de qualquer aparelho que não fosse o próprio
  computador da impressora. **Origem de fora da rede local continua barrada**, e
  a autorização de verdade segue sendo o token. Quem quiser a lista fechada põe
  `"allow_private_network_origins": false` no `config.json`.
- **`/health` é público de propósito** — é a sonda que o painel usa para
  decidir entre imprimir pelo agente ou cair no `window.print()` do navegador.
  Não devolve token, nome de impressora nem qualquer segredo.
- **`/printers` exige token**, justamente por listar nomes de máquina da loja.

## O que **não** é considerado vulnerabilidade

- **Imprimir com um token válido, de uma origem autorizada.** É o
  funcionamento esperado do produto — inclusive de outro aparelho da rede da
  loja (ver "Defesas deliberadas").
- **Requisição sem cabeçalho `Origin` passa pela checagem de origem** — e
  ainda assim **precisa do token**. É deliberado: `Origin` é um cabeçalho que o
  *navegador* preenche em chamada cross-origin, e exigi-lo quebraria clientes
  legítimos que não são navegador. Quem omite o `Origin` não está se passando
  por origem nenhuma; o token continua sendo a autorização de verdade.
- **`/health` respondendo sem token.** Ver acima: é a sonda de liveness.
- **Ausência de HTTPS.** O agente serve em HTTP na rede local por decisão de
  produto: exigir certificado válido para `127.0.0.1`/IP de LAN inviabilizaria
  a instalação numa loja. Quem já está na LAN e consegue farejar o tráfego
  também alcança a impressora diretamente.

## Sobre o token

O token do agente é a **`license_key` do tenant**, reaproveitada. Quem a obtém
consegue mandar imprimir naquela loja.

**O remédio é rotacionar a chave** pelo painel de controle e reconfigurar o
agente com o valor novo — não há revogação separada só do agente.

Por isso: o `config.json` do agente é um arquivo sensível. Guarde-o com as
permissões do usuário que roda o serviço e não o versione.
