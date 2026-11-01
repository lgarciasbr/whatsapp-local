---
name: whatsapp-local
description: Lê conversas do WhatsApp pelo app do Mac (banco local do WhatsApp Desktop) ou por um servidor WAHA, transcreve áudios e vídeos nesta máquina com whisper.cpp (sem API de transcrição) e exporta para Markdown. Com isso resume a conversa, extrai demandas ou analisa negociações. Só leitura - nunca envia, responde nem marca como lida. Use quando pedirem "lê a conversa com o cliente X no zap", "o que o fulano pediu no WhatsApp", "resume a negociação com Y", "extrai as demandas do grupo Z", "transcreve os áudios do cliente", "atualiza o WhatsApp" ou "sincroniza o WhatsApp do CRM". Precisa do comando `wa` instalado (whatsapp-local), de whisper-cli e de ffmpeg.
---
<!--
SPDX-FileCopyrightText: 2026 Filipe (Comunidade Ratos de IA)
SPDX-FileCopyrightText: 2026 Leandro Garcia
SPDX-License-Identifier: MIT
Baseado na primeira versão de Filipe (Comunidade Ratos de IA); alterado por Leandro Garcia.
-->

# whatsapp-local

O comando `wa` lê conversas do WhatsApp, transcreve áudio e vídeo localmente com whisper.cpp e exporta para Markdown. Serve pra resumir conversa com cliente, levantar demandas e entender negociação sem passar pela interface do WhatsApp.

## Escopo

**Faz:** lê conversas, grupos, mensagens e mídia; baixa mídia que falta; transcreve áudio e vídeo nesta máquina; exporta e mantém conversas sincronizadas numa pasta (inclusive no Obsidian CRM).

**Não faz:**
- Não envia mensagem, não responde, não reage, não encaminha e não marca nada como lido. Se pedirem pra mandar mensagem, dizer que esta skill só lê.
- Não usa serviço de transcrição. Se o whisper.cpp não estiver disponível, a saída é instalar e baixar um modelo (com ok do usuário).
- Não vê o que a fonte não tem. App do Mac e WAHA são aparelhos vinculados: só têm o histórico sincronizado quando foram conectados, mais o que chegou depois. Se a conversa parecer começar "do nada", avisar o usuário.

## Contas e fontes

`wa contas` mostra as contas configuradas; `wa contas --testar` confere a conexão. Cada conta tem uma fonte:
- **desktop**: o banco do WhatsApp Desktop nativo do macOS (não do WhatsApp Business nem de Windows). O app não precisa estar aberto, mas o terminal precisa de Acesso Total ao Disco.
- **waha**: a API de um servidor WAHA, só com GET. Funciona no macOS e no Linux. O áudio passa pelo servidor WAHA do usuário antes de chegar aqui; a transcrição continua local.

Use `wa --conta <nome> ...` para escolher a conta; sem `--conta`, vale a conta padrão. Se o usuário tem mais de um número, pergunte de qual conta é a conversa quando não estiver claro.

## Comandos

```bash
wa conversas --busca "fulano"              # acha a conversa: data, grupo?, nome, id
wa inventario --com "fulano" --dias 30     # mídia do período: o que tem aqui e o que falta
wa baixar --com "fulano" --dias 30 --tipos audio,video   # baixa o que falta (ver regras abaixo)
wa transcrever --com "fulano" --dias 30    # áudios e vídeos do período, com cache
wa mensagens --com "fulano" --dias 30      # conversa em ordem, com transcrições embutidas
wa exportar --com "fulano" --dias 30 --destino ~/Notas/WhatsApp   # Markdown + Anexos + Mensagens.json
wa sync                                    # atualiza as conversas configuradas em "sync"
wa modelo                                  # qual modelo do whisper será usado (código 3 = nenhum)
```

- `--com` aceita nome (sem acento e sem diferenciar maiúscula), número com DDI ou id. Se mais de uma conversa bater, sai com código 2 e lista as opções: mostrar pro usuário e repetir com o id.
- Período: `--dias N`, ou `--desde AAAA-MM-DD` e `--ate AAAA-MM-DD` (inclusive).
- `--ids` (em `baixar` e `transcrever`) usa os `#id` que aparecem em `mensagens`.
- `mensagens --json` devolve tudo estruturado (status da mídia, caminho, transcrição).
- `transcrever --idioma pt` força o idioma; `--refazer` ignora o cache.

## Regras de download

- **Fonte desktop: nunca baixar sem o ok do usuário.** O `inventario` confere no servidor do WhatsApp, sem baixar, o que ainda existe. Se faltar arquivo, perguntar, por exemplo: "No período faltam 12 arquivos: 5 áudios (3:10), 2 vídeos e 5 imagens. Dá pra baixar 4 áudios e as 5 imagens; o resto saiu do servidor. Quer baixar?" Opções: só áudio e vídeo (recomendado para transcrever), tudo ou seguir sem baixar. Baixar do servidor por fora do app oficial é uso não oficial; a requisição não leva login, mas é bom o usuário saber.
- **Fonte waha:** a mídia vem do servidor WAHA do próprio usuário. `transcrever` baixa o áudio sozinho. O que já saiu do servidor do WhatsApp fica marcado e não é pedido de novo (cada tentativa leva uns 15 s).
- Áudio e vídeo saem do servidor do WhatsApp em ~2 semanas. Depois disso, só o contato reenviando.

## Modelo do whisper

Antes da primeira transcrição da sessão, rodar `wa modelo`. Se sair com **código 3** (sem modelo):
1. Procurar no disco (outros apps de transcrição costumam trazer): `find ~ /opt /usr/local -maxdepth 6 -name 'ggml-*.bin' -not -name '*.en*' 2>/dev/null`. Achou: usar com `WA_WHISPER_MODEL=<caminho> wa transcrever ...` e contar ao usuário.
2. Não achou: perguntar. **Nunca baixar modelo sem o sim.** `wa baixar-modelo <qual>` sem `--confirmado` só mostra tamanho, destino e espaço livre. Opções: **turbo** (1,6 GB, recomendado), **turbo-leve** (574 MB, para conexão limitada) ou **large-v3** (3,1 GB, o mais preciso e mais lento).
3. Com o sim: `wa baixar-modelo <qual> --confirmado`. Confere tamanho e SHA-256; se a conexão cair, repetir continua de onde parou.

## Fluxo padrão

1. **Conversa e período.** Se o usuário não disse o período, perguntar (sugerir os últimos 30 dias). Usar `wa conversas --busca` quando o nome for vago.
2. **Inventário** e, se faltar arquivo, as regras de download acima.
3. **Transcrever.** Pra muito áudio (mais de 30 min no total), avisar a estimativa antes. Vídeo sem trilha de áudio vira `(vídeo sem áudio)`.
4. **Ler e analisar** com `wa mensagens`. Não colar a conversa inteira pro usuário: entregar a análise pedida.

## Exportação e sync

`wa exportar` cria uma pasta por conversa (`Privado - Nome` ou `Grupo Nome`) com transcript Markdown, `Anexos/` e `Mensagens.json`. O JSON guarda tudo o que já foi exportado: cada exportação junta as mensagens pelo id do WhatsApp, sem apagar o histórico, mesmo que ele tenha sumido da fonte. Não apague o JSON nem os anexos. Transcripts sem `Mensagens.json` são protegidos contra sobrescrita; não contorne a proteção apagando ou renomeando o arquivo.

`wa sync` atualiza as conversas listadas em `"sync"` no config (por nome, número, id ou nome do grupo): o histórico inteiro na primeira vez, depois os últimos `dias`. Um nome só vale se bater com uma única conversa; o id fica gravado e passa a ser usado mesmo que o nome mude. Tem trava contra duas execuções ao mesmo tempo. `wa agendar` mostra (ou `--instalar` instala) o agendamento.

### Atualizações incrementais

Conversas com o mesmo resumo da última leitura bem-sucedida são puladas por até 24 horas. A releitura diária ocorre na próxima execução do sync, não em segundo plano. O resumo do WAHA pode estar desatualizado; use `wa sync --forcar` quando precisar conferir imediatamente ou quando faltar algo recente. O histórico já exportado é preservado. Transcripts com conteúdo igual não são regravados.

### Obsidian CRM (opcional)

Esta skill pertence ao **whatsapp-local**, não ao plugin CRM. O `AGENTS.md` do CRM pode continuar original: não acrescente instruções de WhatsApp nele. Para habilitar a integração, use o configurador separado `python3 integrar_obsidian_crm.py` na pasta do whatsapp-local, depois da instalação principal. Ele não instala nem modifica o plugin: veja https://github.com/lgarciasbr/obsidian-crm.

Ao pedir “atualiza o WhatsApp do CRM”, execute `wa sync`: ele percorre **todas as pessoas do CRM** nas contas configuradas, não apenas pessoas citadas na conversa. Achou pelo telefone, sincroniza; não achou, informa a pendência. Uma pergunta sobre uma pessoa específica pode usar os comandos individuais sem mudar a lista do sync.

Com `"obsidian_crm"` no `"sync"`, o sync também atende o plugin Obsidian CRM (https://github.com/lgarciasbr/obsidian-crm): para cada nota `crm/person`, procura a conversa pelo `phone` em cada conta configurada e exporta uma pasta por conversa em `<pasta do CRM>/WhatsApp/People/`: `<nome>` na conta principal, `<nome> (<conta>)` nas outras, e `<nome> (<número>)` para um segundo número na mesma conta. Telefone sem `+` e com 10 ou 11 dígitos é brasileiro (55); com `+`, o país é o informado. Grupos configurados vão para `Group/<nome>/`. O status fica em `<pasta do CRM>/WhatsApp/Status da sincronização.md`. Só lê as notas do CRM. Uma pessoa só é associada quando o telefone leva a uma única conversa; **nunca associar por nome sozinho** nem confirmar nomes parecidos sem o usuário.

## Análises

Sempre citar data e quem falou nos pontos importantes, e separar o que foi dito por texto do que veio de transcrição (pode ter erro em nome próprio e número).

- **Resumo:** o que aconteceu no período, em ordem, com decisões e pendências no fim.
- **Demandas:** pedidos com data, quem pediu, o que exatamente, prazo se houver, e status (atendido, pendente, sem resposta) inferido pelo resto da conversa.
- **Negociação:** valores e condições propostos por cada lado (com data), objeções, concessões, o que está acordado, o que está em aberto e o próximo passo. Se houver número só em áudio, marcar pra conferir.

Em conversa grande (mais de ~1.500 mensagens no período), sugerir um período menor ou analisar em blocos por semana.

## Privacidade

São conversas privadas, muitas vezes de clientes. Mídia, transcrições e exportações ficam nas pastas configuradas, com permissão só do usuário. Não copiar para repositório nem para lugar compartilhado.
