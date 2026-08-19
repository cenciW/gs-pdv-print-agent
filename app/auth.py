"""Autenticação do agente — token compartilhado + restrição de Origin.

Falha fechada em ambos: sem ``token`` configurado, ``/print`` recusa **tudo**
(nunca aceitar print sem segredo); ``Origin`` fora da lista é recusado mesmo
que o token esteja certo — LAN doméstica/loja não é rede confiável por
padrão, e a única coisa pior que um vizinho de rede conseguir imprimir lixo
na loja é ele conseguir isso mesmo sem token.

Comparação de token via ``secrets.compare_digest`` — nunca ``==`` — mesma
regra já aplicada em todo o monorepo (license-server, menu-server) pra
chaves de API.
"""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, Request, status

from app.config import AgentConfig, origem_autorizada


def verify_token(config: AgentConfig, authorization: str | None) -> None:
    if not config.token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agente sem token configurado — defina AGENT_TOKEN antes de imprimir.",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token ausente")
    presented = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(presented, config.token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")


def verify_origin(config: AgentConfig, origin: str | None) -> None:
    """Recusa origem não autorizada, **pelo mesmo critério do CORS**.

    Origin ausente (ex.: chamada same-origin sem CORS, ou curl local) passa —
    é o header do PRÓPRIO navegador em requisição cross-origin que precisa
    bater; um cliente que simplesmente omite o header não está se passando por
    nenhuma origem específica. Quem autoriza de verdade é o token.

    **Usa `origem_autorizada`, nunca a lista crua.** Na v0.4.0 esta função
    ficou para trás quando a rede local passou a ser aceita: o CORS deixava a
    requisição sair do navegador e ela morria aqui com 403. O sintoma era
    cruel — o painel dizia "Agente conectado" (`/health` não tem auth) e o
    teste de impressão pelo próprio agente funcionava (sem header `Origin`),
    mas imprimir pela tela não fazia nada. Duas checagens de origem são uma a
    mais.
    """
    if origin and not origem_autorizada(config, origin):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Origem não autorizada: {origin}")


def require_auth(request: Request, authorization: str | None = Header(default=None), origin: str | None = Header(default=None)):
    config: AgentConfig = request.app.state.config
    verify_origin(config, origin)
    verify_token(config, authorization)
