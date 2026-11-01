<!--
SPDX-FileCopyrightText: 2026 Leandro Garcia
SPDX-License-Identifier: MIT
-->

# whatsapp-local

[![testes](https://github.com/lgarciasbr/whatsapp-local/actions/workflows/testes.yml/badge.svg)](https://github.com/lgarciasbr/whatsapp-local/actions/workflows/testes.yml)

Lê conversas do WhatsApp, transcreve áudios e vídeos **nesta máquina** com [whisper.cpp](https://github.com/ggml-org/whisper.cpp) e exporta para Markdown. Serve para resumir conversas, levantar demandas e acompanhar negociações, sozinho ou com um agente de IA (Claude Code, Pi, Codex), sem mandar áudio para serviço de transcrição.

- **Só leitura.** Nunca envia, responde, reage nem marca mensagens como lidas.
- **Duas fontes.** O app WhatsApp Desktop do Mac (lendo o banco local) ou um servidor [WAHA](https://waha.devlike.pro) que você controla.
- **Mais de um número.** Cada conta tem nome: `wa --conta pessoal ...`.
- **Sync.** Mantém conversas escolhidas (por nome, número ou grupo) exportadas e transcritas numa pasta, sem perder histórico.
- **Obsidian CRM.** Integração opcional com o plugin [Obsidian CRM](https://github.com/lgarciasbr/obsidian-crm).
- Só a biblioteca padrão do Python. Nenhuma dependência de pip.

## Onde roda

| | macOS | Linux | Windows |
|---|---|---|---|
| Fonte WAHA | sim | sim | não testado |
| Fonte app do Mac | sim (WhatsApp Desktop nativo) | não existe app oficial | não suportado |
| Transcrição, exportação e sync | sim | sim | não testado |
| Agendamento (`wa agendar`) | launchd | systemd ou cron | não |

**Windows não foi testado.** A fonte WAHA usa só HTTP e pode funcionar, mas sem garantia. Ler o app de Windows não é suportado: ele guarda o banco num formato criptografado diferente.

## Instalação

Precisa do Python 3.9+, do `ffmpeg` e do `whisper-cli` (whisper.cpp).

```bash
# macOS
brew install ffmpeg whisper-cpp
# Linux: ffmpeg pelo gerenciador da distribuição; whisper.cpp compilado (instruções no instalador)

git clone https://github.com/lgarciasbr/whatsapp-local.git
cd whatsapp-local
python3 instalar.py
```

O instalador confere as dependências, cria o comando `wa` em `~/.local/bin`, pergunta quais contas configurar (app do Mac e/ou WAHA), guarda a API key do WAHA fora do config e instala a skill para os agentes encontrados.

Depois, um modelo do whisper. Se você já tiver um `ggml-*.bin`, o `wa modelo` acha. Senão:

```bash
wa baixar-modelo turbo                # mostra tamanho e destino
wa baixar-modelo turbo --confirmado   # baixa (1,6 GB) e confere o SHA-256
```

## Uso

```bash
wa contas --testar                         # contas configuradas e conexão
wa conversas --busca "maria"               # acha a conversa
wa inventario --com "Maria Silva" --dias 30
wa transcrever --com "Maria Silva" --dias 30
wa mensagens --com "Maria Silva" --dias 30
wa exportar --com "Maria Silva" --dias 30 --destino ~/Notas/WhatsApp
wa --conta pessoal conversas               # outra conta
```

`--com` aceita nome, número com DDI ou id. Se um nome bater com mais de uma conversa, o `wa` lista as opções e não escolhe sozinho.

A exportação cria uma pasta por conversa com o transcript em Markdown, `Anexos/` (prontos para o Obsidian) e `Mensagens.json`. O JSON guarda tudo o que já foi exportado: as próximas exportações juntam as mensagens novas pelo id do WhatsApp, sem apagar o histórico, mesmo que ele tenha sumido da fonte.

## Configuração

`~/.config/whatsapp-local/config.json` (veja [exemplos/config.exemplo.json](exemplos/config.exemplo.json)):

```json
{
  "dados": "~/.local/share/whatsapp-local",
  "conta_padrao": "trabalho",
  "contas": {
    "trabalho": {"fonte": "waha", "url": "https://waha.exemplo.com", "sessao": "default"},
    "mac": {"fonte": "desktop"}
  },
  "whisper": {"idioma": "pt"}
}
```

- **`dados`**: onde ficam a mídia baixada e as transcrições (uma pasta por conta). Uma conta pode ter `"dados"` próprio; duas contas do mesmo número (app do Mac e WAHA) podem apontar para a mesma pasta.
- **API key do WAHA**: na variável `WAHA_API_KEY_<CONTA>` (ex.: `WAHA_API_KEY_TRABALHO`) ou em `segredos.env`, ao lado do config, com permissão só do usuário. Nunca no `config.json`.
- **`whisper`**: `idioma`, e opcionalmente `modelo` (caminho do `ggml-*.bin`) e `executavel` (caminho do `whisper-cli`).

## Sync

```json
"sync": {
  "dias": 30,
  "destino": "~/Notas/WhatsApp",
  "conversas": [
    {"conversa": "Maria Silva"},
    {"conversa": "+5511999999999", "conta": "pessoal"},
    {"conversa": "Equipe Projeto X", "destino": "~/Notas/Projeto X"}
  ]
}
```

`wa sync` baixa (pelo WAHA), transcreve e exporta cada conversa: o histórico inteiro na primeira vez, depois os últimos `dias`. Na primeira vez, o nome é resolvido e o id da conversa fica gravado em `<dados>/sync-estado.json`; depois, o sync segue pelo id mesmo que o nome mude. Uma conversa com problema não para as outras.

### Sync incremental

Depois de uma leitura bem-sucedida, o sync compara a data da última mensagem no resumo da conversa. Sem mudança, adia a leitura e não regrava os transcripts. Esse resumo pode ficar desatualizado no WAHA: por isso, relê ao menos uma vez a cada 24 horas **quando o sync é executado**. Para conferir imediatamente: `wa sync --forcar`.

Mensagens na mesma marca de tempo, edições e mudanças que não alteram o resumo podem esperar essa releitura. O histórico exportado continua preservado, inclusive mensagens removidas da fonte. Falhas de exportação ou transcrição não habilitam o atalho. Mesmo numa releitura, arquivos com conteúdo idêntico não são regravados.

Para rodar periodicamente: `wa agendar` mostra o agendamento; `wa agendar --instalar` instala (launchd no macOS, timer do systemd ou cron no Linux), a cada 30 minutos por padrão.

## Integração com o Obsidian CRM

Para quem usa o plugin [Obsidian CRM](https://github.com/lgarciasbr/obsidian-crm):

```json
"sync": {
  "obsidian_crm": {
    "vault": "~/Obsidian/Meu Vault",
    "contas": ["trabalho", "pessoal"],
    "pessoas": {"Maria Silva": "5511999999999@c.us"},
    "grupos": [{"conversa": "Equipe Projeto X", "nome": "Projeto X"}]
  }
}
```

Para cada pessoa do CRM (nota `type: crm/person`), o sync procura a conversa pelo `phone` em cada conta de `contas` e exporta para `<pasta do CRM>/WhatsApp/People/`. Os grupos listados vão para `Group/<nome>/`. A pasta do CRM vem das configurações do plugin. O resultado fica em `<pasta do CRM>/WhatsApp/Status da sincronização.md`.

- **Uma pasta por conversa.** Na primeira conta de `contas`, a pasta é `<nome>`; nas outras, `<nome> (<conta>)`. Se a mesma conta tiver outra conversa da pessoa (um número antigo, por exemplo), a extra leva o número: `<nome> (+55 11 91234-5678)`.
- **Telefone.** Sem `+` e com 10 ou 11 dígitos, vale o país padrão (`ddi_padrao`, 55). Com `+`, o país já está explícito. Celulares brasileiros com e sem o nono dígito são o mesmo número.
- Numa conta, a pessoa só é associada quando o telefone leva a uma única conversa. Nunca por nome. Quem não tem telefone no CRM fica pendente, a menos que esteja em `pessoas`.
- Na primeira exportação de cada conversa vem o histórico inteiro; depois, só os últimos `dias`.
- As notas do CRM só são lidas; o sync escreve apenas dentro de `WhatsApp/`.

## O que saber

- **Histórico.** O app do Mac e o WAHA são aparelhos vinculados: só têm o que o WhatsApp sincronizou quando foram conectados, mais o que chegou depois. O que já foi exportado continua no `Mensagens.json`.
- **Mídia expira.** Áudio e vídeo saem do servidor do WhatsApp em umas 2 semanas. Depois disso, só reenviando. Por isso vale rodar o sync com frequência.
- **Fonte desktop.** O terminal (e o agendamento) precisa de Acesso Total ao Disco. Baixar mídia que o app não baixou consulta o servidor do WhatsApp por fora do app oficial; o `wa` só faz isso quando pedido.
- **Fonte WAHA.** O áudio passa pelo seu servidor WAHA antes de chegar aqui; a transcrição continua local. Testado com o engine WEBJS. Ler uma conversa inteira pode levar uns 30 s; o sync lê só a janela recente.
- **Privacidade.** São conversas privadas. Mídia, transcrições e exportações ficam nas pastas que você escolher, com permissão só do seu usuário.

## Testes

```bash
python3 -m unittest discover -s tests -t .
```

Os testes usam um WAHA falso, um banco do app do Mac falso e um vault de CRM falso. Nenhum dado real. Rodam a cada mudança no macOS e no Linux, com Python 3.9, 3.12 e 3.13.

## Créditos

- **Filipe, da Comunidade Ratos de IA**: primeira versão (`whatsapp-desktop-local`): leitura do WhatsApp Desktop do Mac, decifragem da mídia, transcrição local com whisper.cpp e a skill.
- **Leandro Garcia**: fonte WAHA, contas, sync, exportação, integração com o Obsidian CRM, instalador e testes, e as alterações nos arquivos da primeira versão.

Cada arquivo diz no cabeçalho de quem é (padrão [REUSE](https://reuse.software)/SPDX). Histórico em [CHANGELOG.md](CHANGELOG.md).

## Licença

[MIT](LICENSE). Copyright (c) 2026 Filipe (Comunidade Ratos de IA) e Leandro Garcia.
