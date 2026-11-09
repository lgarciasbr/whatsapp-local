# Changelog

## Não publicado

- Fonte wacli: lê o espelho local do [wacli](https://wacli.sh) (`wacli.db`), sem parear nem enviar. A mídia que falta é pedida ao comando `wacli` em modo somente leitura. Conversa privada com mapa lid usa o mesmo `@lid` das outras fontes, para não quebrar a pasta já exportada.
- Agendamento no macOS por um app próprio (**WhatsApp Local Sync**): o launchd abre o app, e o macOS pede a permissão para pastas protegidas (Documentos, iCloud Drive, OneDrive) em nome dele, sem Acesso Total ao Disco para o Python. O app só é recriado quando algo muda, para não perder a permissão.
- Logo do projeto (`assets/logo.svg`), também usado como ícone do app.
- `wa sync` avisa quando não há nada configurado para sincronizar.
- A documentação descreve o que esta versão faz (não envia mensagens) em vez de prometer "nunca envia".
- Correção: datas do WAHA em milissegundos quebravam a leitura da conversa.
- Sync incremental: conversas sem mudança no resumo do WAHA são puladas, com releitura completa a cada 24 horas e `wa sync --forcar`.
- Integração com o Obsidian CRM: procura em todas as contas configuradas, assume o Brasil (`+55`) em telefones sem código do país, uma pasta por conversa e histórico completo na primeira exportação.
- Configurador da integração com o Obsidian CRM (`integrar_obsidian_crm.py`) separado do instalador principal.
- Correção: o filtro de data do WAHA (engine WEBJS) pulava mensagens anteriores a uma mensagem sem data; o filtro agora é feito localmente.
- O sync só busca a lista de contatos para grupos, o que deixou a execução bem mais rápida.

## 0.1.0 - 2026-10-31

Primeira versão publicada, por Leandro Garcia, a partir da primeira versão de Filipe, da Comunidade Ratos de IA.

Da versão de Filipe, da Comunidade Ratos de IA (`whatsapp-desktop-local`): leitura do banco do WhatsApp Desktop do Mac, download e decifragem da mídia que o app não baixou, transcrição local com whisper.cpp e as regras de uso da skill.

Novo nesta versão:
- Fonte WAHA, além do app do Mac, e contas nomeadas (mais de um número).
- Pasta de dados configurável; a API key do WAHA fica fora do config.
- Exportação para Markdown, `Anexos/` e `Mensagens.json`, juntando pelo id do WhatsApp sem perder histórico.
- `wa sync` por nome, número ou grupo, com o id gravado na primeira resolução.
- Integração opcional com o plugin Obsidian CRM.
- `wa agendar` (launchd, systemd ou cron), instalador e testes com fontes falsas.
